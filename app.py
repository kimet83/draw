import json
import os
from datetime import datetime
from collections import Counter
from secrets import SystemRandom  # ✅ CSPRNG
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, make_response
import pandas as pd

# --------------------------------
# Flask & 전역 설정
# --------------------------------
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 업로드 크기 제한: 10MB
# 앱 설정(기존 설정 아래쪽에 이어서)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'luka1983')  # 세션 서명 키
app.config['ACCESS_CODE'] = os.environ.get('ACCESS_CODE', 'kamt2025')               # 접근 코드(환경변수 권장)

# 쿠키 보안 옵션 (내부망 HTTP라면 SECURE=False 유지)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # HTTPS 환경이면 True로 바꾸세요
# 암호학적 난수 생성기
_secure_rand = SystemRandom()  # os.urandom 기반, 예측 불가

# 동시성 보호(간단 락)
from threading import RLock
_state_lock = RLock()  # 전역 상태 보호

remaining_entries = []
selected_entries = []
current_filename = None
last_draw_count = 0  # 최근 추첨 인원 수

# 경품 제한 저장 파일
GIFT_LIMITS_FILE = 'gift_limits.json'

# 경품별 최대 당첨 인원 제한 (기본값)
gift_limits = {
    "1등 해외연수": 1,
    "2등 다이슨 에어랩 코안다2x™": 1,
    "3등 다이슨 에어랩 i.d.™": 1,
    "4등 커피머신": 10,
    "5등 스타벅스상품권": 40
}

def load_gift_limits():
    """경품 제한 로드 (없으면 기본값 유지)"""
    global gift_limits
    try:
        if os.path.exists(GIFT_LIMITS_FILE):
            with open(GIFT_LIMITS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    gift_limits = data
    except Exception:
        # 손상된 파일 등은 무시하고 기본값 사용
        pass

def save_gift_limits():
    """경품 제한 저장(원자적 쓰기)"""
    tmp = GIFT_LIMITS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(gift_limits, f, ensure_ascii=False, indent=2)
    os.replace(tmp, GIFT_LIMITS_FILE)  # 원자적 교체

def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )

def allowed_mimetype(file_storage):
    # 간단 MIME 체크 (엑셀: openxml)
    mt = (file_storage.mimetype or '').lower()
    return 'spreadsheetml' in mt or mt in ('application/octet-stream',)

@app.route('/access', methods=['GET', 'POST'])
def access():
    # 이미 인증되어 있으면 next로 회송
    if session.get('access_granted'):
        dest = request.args.get('next') or url_for('index')
        return redirect(dest)

    error = None
    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        target = app.config.get('ACCESS_CODE', '').strip()
        if not target:
            # ACCESS_CODE 미설정 시, 폼의 코드가 비어있지 않으면 통과(임시)
            ok = bool(code)
        else:
            ok = (code == target)

        if ok:
            # ✅ 브라우저 세션 동안만 유지(만료 없음)
            session.permanent = False
            session['access_granted'] = True
            dest = request.args.get('next') or url_for('index')
            return redirect(dest)
        else:
            error = '접근코드가 올바르지 않습니다.'

    # 간단한 템플릿 렌더 (별도 access.html이 있으면 render_template 사용)
    return ("""
<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<title>접근코드 입력</title>
</head>
<body class="bg-body d-flex align-items-center" style="min-height:100vh">
  <div class="container" style="max-width:420px">
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title text-center mb-3">접근코드 입력</h5>
        """ + (f'<div class="alert alert-danger py-2">{error}</div>' if error else '') + """
        <form method="post">
          <div class="mb-3">
            <label class="form-label">코드</label>
            <input type="password" name="code" class="form-control" autocomplete="current-password" required>
          </div>
          <button class="btn btn-primary w-100" type="submit">입장</button>
        </form>
        <div class="text-muted small mt-3">브라우저를 닫기 전까지 재입력 없이 사용됩니다.</div>
      </div>
    </div>
  </div>
</body></html>
""")


@app.route("/", methods=["GET", "POST"])
def index():
    with _state_lock:
        return render_template("index.html", remaining=len(remaining_entries), total=len(selected_entries))

@app.route("/upload", methods=["POST"])
def upload():
    """엑셀 업로드: 면허번호/이름 필수, 소속기관은 공란 허용(빈 문자열로 통일)"""
    global remaining_entries, selected_entries, current_filename

    file = request.files.get('file')
    if not file:
        return "파일이 없습니다.", 400

    if not allowed_file(file.filename):
        return "허용되지 않은 파일 확장자입니다. (xlsx)", 400

    if not allowed_mimetype(file):
        return "허용되지 않은 MIME 타입입니다.", 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(filepath)

    # 엑셀 로드
    try:
        df = pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        return f"엑셀 파일을 읽는 중 오류: {e}", 400

    required = {'면허번호', '이름', '소속기관'}
    if not required.issubset(df.columns):
        return "엑셀 파일에 '면허번호', '이름', '소속기관' 열이 있어야 합니다.", 400

    # ✅ dropna() 제거: 면허번호/이름만 필수, 소속기관은 빈 문자열 허용
    df = df[['면허번호', '이름', '소속기관']].copy()

    # ✅ 문자열 정규화 유틸
    def norm_str(x):
        if pd.isna(x):
            return ''
        s = str(x).strip()
        # 엑셀에서 숫자로 읽힌 면허번호 '1234.0' 같은 꼬리 제거
        return s

    # 각 컬럼 정규화
    df['면허번호'] = df['면허번호'].apply(norm_str)
    # 면허번호가 숫자형으로 들어오며 'xxxxx.0' 꼬리가 생기는 경우 제거
    df['면허번호'] = df['면허번호'].str.replace(r'\.0$', '', regex=True)

    df['이름'] = df['이름'].apply(norm_str)

    # 소속기관은 공란 허용 → NaN/ "nan" → '' 로 통일
    df['소속기관'] = df['소속기관'].apply(norm_str).replace({'nan': ''})

    # ✅ 필수값 검증: 면허번호 & 이름만 필수
    df = df[(df['면허번호'] != '') & (df['이름'] != '')]

    # ✅ 과도한 길이 방어
    df['면허번호'] = df['면허번호'].str.slice(0, 64)
    df['이름'] = df['이름'].str.slice(0, 64)
    df['소속기관'] = df['소속기관'].str.slice(0, 128)

    # (선택) 중복 제거를 원한다면 주석 해제 (면허번호+이름 기준)
    # df.drop_duplicates(subset=['면허번호', '이름'], keep='first', inplace=True)

    with _state_lock:
        current_filename = filename
        remaining_entries = df.to_dict(orient='records')
        selected_entries.clear()

    return redirect(url_for('index'))

@app.route("/draw", methods=["POST"])
def draw():
    global remaining_entries, current_filename, last_draw_count
    try:
        count_raw = request.form.get("count")
        gift = (request.form.get("gift") or "").strip()
        if not count_raw or not gift:
            return jsonify({"error": "올바른 인원 수와 경품명을 입력하세요."}), 400

        count = int(count_raw)
        if count <= 0:
            return jsonify({"error": "추첨 인원 수는 1 이상이어야 합니다."}), 400

        # 제외 대상 처리 (선택)
        exclude = request.form.get("exclude")
        if exclude:
            try:
                exclude = json.loads(exclude)
                with _state_lock:
                    remaining_entries[:] = [
                        e for e in remaining_entries
                        if not (
                            (e.get("면허번호", "") == (exclude.get("면허번호", ""))) and
                            (e.get("이름", "") == (exclude.get("이름", ""))) and
                            (e.get("소속기관", "") == (exclude.get("소속기관", "")))
                        )
                    ]
            except Exception as e:
                return jsonify({"error": f"제외 처리 오류: {str(e)}"}), 400

    except (ValueError, TypeError):
        return jsonify({"error": "올바른 인원 수와 경품명을 입력하세요."}), 400

    # 경품 제한 변경(선택)
    limit_override = request.form.get("limit")
    if limit_override:
        try:
            limit_override = int(limit_override)
            if limit_override < 0 or limit_override > 100000:
                return jsonify({"error": "경품 인원 제한 값이 비정상적입니다."}), 400
            with _state_lock:
                gift_limits[gift] = limit_override
                save_gift_limits()
        except ValueError:
            return jsonify({"error": "경품 인원 제한은 숫자여야 합니다."}), 400

    with _state_lock:
        # 경품별 제한 확인
        existing_count = sum(1 for e in selected_entries if e.get('경품') == gift)
        limit = gift_limits.get(gift)
        if limit is not None and existing_count + count > limit:
            return jsonify({"error": f"{gift} 경품은 최대 {limit}명까지 추첨 가능합니다. 현재 {existing_count}명 당첨됨."}), 400

        if count > len(remaining_entries):
            return jsonify({"error": f"남은 인원보다 많이 추첨할 수 없습니다. (남은 인원: {len(remaining_entries)})"}), 400

        # 암호학적 난수로 비복원 샘플링
        selected = _secure_rand.sample(remaining_entries, count)

        # 남은 목록 갱신
        selected_set = {(s['면허번호'], s['이름'], s.get('소속기관', '')) for s in selected}
        remaining_entries = [
            p for p in remaining_entries
            if (p['면허번호'], p['이름'], p.get('소속기관', '')) not in selected_set
        ]

        # 경품 태깅 & 결과 누적
        for s in selected:
            s = dict(s)  # 방어적 복사
            s['경품'] = gift
            # 소속기관 키가 없거나 None이면 빈 문자열 보정
            if not s.get('소속기관'):
                s['소속기관'] = ''
            selected_entries.append(s)

        last_draw_count = count
        log_draw_result(current_filename, selected)

    return jsonify({
        "result": selected,
        "remaining": len(remaining_entries),
        "total": len(selected_entries)
    })

@app.route("/state")
def state():
    with _state_lock:
        gift_counts = Counter(e.get('경품') for e in selected_entries)
        return jsonify({
            "remaining": len(remaining_entries),
            "result": selected_entries[-last_draw_count:][::-1],
            "all": selected_entries[::-1],
            "total": len(selected_entries),
            "gift_counts": gift_counts
        })

@app.route("/clear", methods=["POST"])
def clear():
    with _state_lock:
        selected_entries.clear()
    return jsonify({"success": True})

@app.route("/reset", methods=["POST"])
def reset():
    global remaining_entries, selected_entries, current_filename
    with _state_lock:
        remaining_entries.clear()
        selected_entries.clear()
        current_filename = None
    return jsonify({"success": True})

def log_draw_result(filename, entries):
    os.makedirs('logs', exist_ok=True)
    log_file = 'logs/draw_log.csv'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for e in entries:
        rows.append({
            "시각": timestamp,
            "엑셀파일": filename or "unknown.xlsx",
            "면허번호": e.get('면허번호', ''),
            "이름": e.get('이름', ''),
            "소속기관": e.get('소속기관', ''),
            "경품": e.get('경품', '')
        })
    df = pd.DataFrame(rows)
    if os.path.exists(log_file):
        df.to_csv(log_file, mode='a', index=False, header=False, encoding='utf-8-sig', lineterminator='\n')
    else:
        df.to_csv(log_file, index=False, encoding='utf-8-sig', lineterminator='\n')

@app.route("/delete", methods=["POST"])
def delete():
    global selected_entries
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        with _state_lock:
            idx = next((
                i for i, e in enumerate(selected_entries)
                if (
                    (e.get('면허번호', '') == data.get('면허번호', '')) and
                    (e.get('이름', '') == data.get('이름', '')) and
                    (e.get('소속기관', '') == data.get('소속기관', '')) and
                    (e.get('경품', '') == data.get('경품', ''))
                )
            ), None)

            if idx is not None:
                removed = selected_entries.pop(idx)
                log_delete_result(removed)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def log_delete_result(entry):
    os.makedirs('logs', exist_ok=True)
    log_file = 'logs/delete_log.csv'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    df = pd.DataFrame([{
        "삭제시각": timestamp,
        "면허번호": entry.get('면허번호', ''),
        "이름": entry.get('이름', ''),
        "소속기관": entry.get('소속기관', ''),
        "경품": entry.get('경품', '')
    }])
    if os.path.exists(log_file):
        df.to_csv(log_file, mode='a', index=False, header=False, encoding='utf-8-sig', lineterminator='\n')
    else:
        df.to_csv(log_file, index=False, encoding='utf-8-sig', lineterminator='\n')

@app.route("/limits")
def get_limits():
    with _state_lock:
        return jsonify(gift_limits)

@app.route("/logout", methods=["POST"])
def logout():
    # 세션 비우기 (브라우저 세션 쿠키로만 인증하므로 이것만으로 충분)
    session.clear()

    # 세션 쿠키까지 깔끔하게 제거(선택이지만 권장)
    resp = redirect(url_for("access"))
    cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
    resp.delete_cookie(
        cookie_name,
        path="/",
        samesite=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        secure=app.config.get("SESSION_COOKIE_SECURE", False)
    )
    return resp
    
# @app.route 들 아래 아무 곳에 추가
@app.before_request
def _require_access_code():
    # 접근 허용 경로 (로그인/정적/헬스체크 등)
    path = request.path or '/'
    if (path.startswith('/static')
        or path in ('/access', '/favicon.ico', '/healthz')):
        return  # 통과

    # 세션으로 인증 확인
    if session.get('access_granted'):
        return  # 통과

    # JSON API 요청이면 401 반환, 그 외에는 /access로 리다이렉트
    wants_json = request.accept_mimetypes.best == 'application/json' or path.startswith('/api')
    if wants_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': 'access required'}), 401
    # 로그인 페이지로 이동 (원래 가려던 경로 next로 보존)
    return redirect(url_for('access', next=path))


if __name__ == "__main__":
    os.makedirs('uploads', exist_ok=True)
    load_gift_limits()
    # 프로덕션에선 debug=False 권장, 그리고 리버스 프록시/HTTPS/접근제어 적용 권장
    app.run(debug=True, port=5000)
