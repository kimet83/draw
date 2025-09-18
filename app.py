import json
import os
from datetime import datetime
from collections import Counter
from secrets import SystemRandom  # ✅ CSPRNG
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, url_for, jsonify
import pandas as pd

# --------------------------------
# Flask & 전역 설정
# --------------------------------
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # ✅ 업로드 크기 제한: 10MB

# 암호학적 난수 생성기
_secure_rand = SystemRandom()  # ✅ os.urandom 기반, 예측 불가

# 동시성 보호(간단 락)
from threading import RLock
_state_lock = RLock()  # ✅ 전역 상태 보호

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
    os.replace(tmp, GIFT_LIMITS_FILE)  # ✅ 원자적 교체

def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )

def allowed_mimetype(file_storage):
    # 간단 MIME 체크 (엑셀: openxml)
    mt = (file_storage.mimetype or '').lower()
    return 'spreadsheetml' in mt or mt in ('application/octet-stream',)

@app.route("/", methods=["GET", "POST"])
def index():
    with _state_lock:
        return render_template("index.html", remaining=len(remaining_entries), total=len(selected_entries))

@app.route("/upload", methods=["POST"])
def upload():
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

    # 저장
    file.save(filepath)

    # 엑셀 로드
    try:
        df = pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        return f"엑셀 파일을 읽는 중 오류: {e}", 400

    required = {'면허번호', '이름', '소속기관'}
    if not required.issubset(df.columns):
        return "엑셀 파일에 '면허번호', '이름', '소속기관' 열이 있어야 합니다.", 400

    # NaN 제거 & 레코드 구성
    df = df[list(required)].dropna()
    # 간단 길이 제한(이상치 방지)
    for col, limit in (('면허번호', 64), ('이름', 64), ('소속기관', 128)):
        df[col] = df[col].astype(str).str.slice(0, limit)

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
                            e.get("면허번호") == exclude.get("면허번호")
                            and e.get("이름") == exclude.get("이름")
                            and e.get("소속기관") == exclude.get("소속기관")
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

        # ✅ 암호학적 난수로 비복원 샘플링
        selected = _secure_rand.sample(remaining_entries, count)

        # 남은 목록 갱신
        selected_set = { (s['면허번호'], s['이름'], s['소속기관']) for s in selected }
        remaining_entries = [
            p for p in remaining_entries
            if (p['면허번호'], p['이름'], p['소속기관']) not in selected_set
        ]

        # 경품 태깅 & 결과 누적
        for s in selected:
            s = dict(s)  # 방어적 복사
            s['경품'] = gift
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
                    e.get('면허번호') == data.get('면허번호') and
                    e.get('이름') == data.get('이름') and
                    e.get('소속기관') == data.get('소속기관') and
                    e.get('경품') == data.get('경품')
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

if __name__ == "__main__":
    os.makedirs('uploads', exist_ok=True)
    load_gift_limits()
    # 프로덕션에선 debug=False 권장, 그리고 리버스 프록시/HTTPS/접근제어 적용 권장
    app.run(debug=True, port=5000)
