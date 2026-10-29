import os, uuid
from flask import Flask, request, jsonify

app = Flask(__name__)
UPLOAD_DIR = "/srv/files/uploads"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://94.141.97.249").rstrip("/")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No selected file"}), 400
    if not f.filename.lower().endswith((".html", ".htm")):
        return jsonify({"error": "Only .html/.htm files allowed"}), 400
    ext = os.path.splitext(f.filename)[1]
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    f.save(path)
    url = f"{PUBLIC_URL}/files/uploads/{fname}"
    return jsonify({"url": url, "filename": fname}), 200

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
