import json

GIFT_LIMITS_FILE = 'gift_limits.json'

def load_gift_limits():
    global gift_limits
    if os.path.exists(GIFT_LIMITS_FILE):
        with open(GIFT_LIMITS_FILE, 'r', encoding='utf-8') as f:
            gift_limits = json.load(f)  # update → 대입

def save_gift_limits():
    with open(GIFT_LIMITS_FILE, 'w', encoding='utf-8') as f:
        json.dump(gift_limits, f, ensure_ascii=False, indent=2)
from flask import Flask, render_template, request, redirect, url_for, jsonify
import pandas as pd
import random
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from collections import Counter

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}

remaining_entries = []
selected_entries = []
current_filename = None
last_draw_count = 0  # 최근 추첨된 인원 수

# 경품별 최대 당첨 인원 제한
gift_limits = {
    "1등 해외연수": 1,
    "2등 다이슨 에어랩 코안다2x™": 1,
    "3등 다이슨 에어랩 i.d.™": 1,
    "4등 커피머신": 10,
    "5등 스타벅스상품권": 40
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html", remaining=len(remaining_entries), total=len(selected_entries))

@app.route("/upload", methods=["POST"])
def upload():
    global remaining_entries, selected_entries, current_filename
    file = request.files['file']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        current_filename = filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        df = pd.read_excel(filepath)
        if not {'면허번호', '이름', '소속기관'}.issubset(df.columns):
            return "엑셀 파일에 '면허번호', '이름', '소속기관' 열이 있어야 합니다.", 400

        remaining_entries = df[['면허번호', '이름', '소속기관']].dropna().to_dict(orient='records')
        selected_entries.clear()
        return redirect(url_for('index'))

@app.route("/draw", methods=["POST"])
def draw():
    global remaining_entries, current_filename, last_draw_count
    try:
        count = int(request.form.get("count"))
        gift = request.form.get("gift", "").strip()
        if not gift:
            raise ValueError("경품명이 없습니다.")
        exclude = request.form.get("exclude")
        if exclude:
            try:
                import json
                exclude = json.loads(exclude)
                remaining_entries = [e for e in remaining_entries if not (
                    e["면허번호"] == exclude["면허번호"] and
                    e["이름"] == exclude["이름"] and
                    e["소속기관"] == exclude["소속기관"]
                )]
            except Exception as e:
                return jsonify({"error": f"제외 처리 오류: {str(e)}"}), 400
            
    except (ValueError, TypeError):
        return jsonify({"error": "올바른 인원 수와 경품명을 입력하세요."}), 400

    limit_override = request.form.get("limit")
    if limit_override:
        try:
            limit_override = int(limit_override)
            gift_limits[gift] = limit_override
            save_gift_limits()  # 경품 제한 저장
        except ValueError:
            return jsonify({"error": "경품 인원 제한은 숫자여야 합니다."}), 400

    # 경품별 제한 확인
    existing_count = sum(1 for e in selected_entries if e['경품'] == gift)
    limit = gift_limits.get(gift)
    if limit is not None and existing_count + count > limit:
        return jsonify({"error": f"{gift} 경품은 최대 {limit}명까지 추첨 가능합니다. 현재 {existing_count}명 당첨됨."}), 400

    if count > len(remaining_entries):
        return jsonify({"error": f"남은 인원보다 많이 추첨할 수 없습니다. (남은 인원: {len(remaining_entries)})"}), 400

    selected = random.sample(remaining_entries, count)
    remaining_entries = [p for p in remaining_entries if p not in selected]
    for s in selected:
        s['경품'] = gift
        selected_entries.append(s)

    last_draw_count = count  # ✅ 저장
    log_draw_result(current_filename, selected)

    return jsonify({"result": selected, "remaining": len(remaining_entries), "total": len(selected_entries)})


@app.route("/state")
def state():
    # 경품별 개수 계산
    gift_counts = Counter(e['경품'] for e in selected_entries)

    return jsonify({
        "remaining": len(remaining_entries),
        "result": selected_entries[-last_draw_count:][::-1],
        "all": selected_entries[::-1],
        "total": len(selected_entries),
        "gift_counts": gift_counts  # ✅ 경품별 당첨자 수 포함
    })

@app.route("/clear", methods=["POST"])
def clear():
    selected_entries.clear()
    return jsonify({"success": True})

@app.route("/reset", methods=["POST"])
def reset():
    global remaining_entries, selected_entries, current_filename
    remaining_entries.clear()
    selected_entries.clear()
    current_filename = None
    return jsonify({"success": True})

def log_draw_result(filename, entries):
    os.makedirs('logs', exist_ok=True)
    log_file = 'logs/draw_log.csv'
    log_entries = []
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for e in entries:
        log_entries.append({
            "시각": timestamp,
            "엑셀파일": filename or "unknown.xlsx",
            "면허번호": e['면허번호'],
            "이름": e['이름'],
            "소속기관": e['소속기관'],
            "경품": e['경품']
        })
    df = pd.DataFrame(log_entries)
    if os.path.exists(log_file):
        df.to_csv(log_file, mode='a', index=False, header=False, encoding='utf-8-sig')
    else:
        df.to_csv(log_file, index=False, encoding='utf-8-sig')

@app.route("/delete", methods=["POST"])
def delete():
    global selected_entries
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        to_delete = None
        for e in selected_entries:
            if (
                e['면허번호'] == data['면허번호'] and
                e['이름'] == data['이름'] and
                e['소속기관'] == data['소속기관'] and
                e['경품'] == data['경품']
            ):
                to_delete = e
                break

        if to_delete:
            selected_entries.remove(to_delete)
            log_delete_result(to_delete)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def log_delete_result(entry):
    os.makedirs('logs', exist_ok=True)
    log_file = 'logs/delete_log.csv'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = {
        "삭제시각": timestamp,
        "면허번호": entry['면허번호'],
        "이름": entry['이름'],
        "소속기관": entry['소속기관'],
        "경품": entry['경품']
    }

    df = pd.DataFrame([log_entry])
    if os.path.exists(log_file):
        df.to_csv(log_file, mode='a', index=False, header=False, encoding='utf-8-sig')
    else:
        df.to_csv(log_file, index=False, encoding='utf-8-sig')

# Optionally add a /limits API to expose the current limits to the frontend:
@app.route("/limits")
def get_limits():
    return jsonify(gift_limits)



if __name__ == "__main__":
    os.makedirs('uploads', exist_ok=True)
    load_gift_limits()  # 경품 제한 로드
    app.run(debug=True, port=5000)