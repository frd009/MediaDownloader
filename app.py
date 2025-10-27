import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import shutil
import base64
import time 
import sys # <-- PERBAIKAN: Tambahkan import sys

# --- Konfigurasi ---
DOWNLOAD_DIR = "downloaded_videos"
SERVER_PORT = 5000
DOWNLOAD_TIMEOUT = 300  # 5 menit

INSTAGRAM_COOKIES = "instagram_cookies.txt"
TWITTER_COOKIES = "twitter_cookies.txt" 
TIKTOK_COOKIES = "tiktok_cookies.txt" 
YOUTUBE_COOKIES = "youtube_cookies.txt"

# Standar User-Agent untuk menyamar sebagai browser
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

# --- PERSIAPAN DEPLOYMENT: Tulis Cookies dari Environment Variables ---
def write_cookies_from_env():
    print("Memeriksa environment variables untuk cookies...")
    
    cookie_vars = {
        INSTAGRAM_COOKIES: os.environ.get('INSTA_COOKIE_B64_DATA'),
        TWITTER_COOKIES: os.environ.get('TWITTER_COOKIE_B64_DATA'),
        TIKTOK_COOKIES: os.environ.get('TIKTOK_COOKIE_B64_DATA'),
        YOUTUBE_COOKIES: os.environ.get('YOUTUBE_COOKIE_B64_DATA')
    }

    for filename, data_b64 in cookie_vars.items():
        try:
            if data_b64:
                with open(filename, 'wb') as f:
                    f.write(base64.b64decode(data_b64))
                print(f"Berhasil menulis {filename} dari env variable Base64.")
            else:
                print(f"Info: {filename} env variable (B64) tidak ditemukan.")
        except Exception as e:
            print(f"ERROR: Gagal mendekode atau menulis {filename}. {e}")

# --- Akhir Persiapan Deployment ---

app = Flask(__name__)

# --- Konfigurasi CORS (Sudah Benar) ---
ALLOWED_FRONTEND_ORIGINS = [
    "https.mediadown.kesug.com",      # Domain utama
    "https://www.mediadown.kesug.com" # Jika pengguna mengakses via www
]

CORS(app, resources={
    r"/api/*": {
        "origins": ALLOWED_FRONTEND_ORIGINS,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    },
    r"/downloads/*": {
        "origins": ALLOWED_FRONTEND_ORIGINS,
        "methods": ["GET", "OPTIONS"], 
        "allow_headers": ["Content-Type"]
    }
})


if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- FUNGSI HELPER: Mengambil Format Video (Langkah 1) ---
def get_video_formats(media_url):
    print(f"Mengambil format untuk: {media_url}")
    
    command = [
        sys.executable, '-m', 'yt_dlp', # <-- PERBAIKAN: Gunakan sys.executable
        '-j', 
        '--no-check-certificate',
        '--geo-bypass',
        '--no-playlist',
        '--user-agent', USER_AGENT,
        media_url
    ]
    
    if "twitter.com" in media_url or "x.com" in media_url:
        print("Mendeteksi URL Twitter/X, menambahkan file cookie...")
        if os.path.exists(TWITTER_COOKIES):
            command.extend(['--cookies', TWITTER_COOKIES])
    
    if "youtube.com" in media_url or "youtu.be" in media_url:
        print("Mendeteksi URL YouTube, menambahkan file cookie...")
        if os.path.exists(YOUTUBE_COOKIES):
            command.extend(['--cookies', YOUTUBE_COOKIES])
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            errors='replace',  
            timeout=60
        )
        
        final_title = "Judul Tidak Diketahui"
        
        # Ambil judul dari JSON baris pertama
        for line in result.stdout.strip().split('\n'):
            data = json.loads(line)
            final_title = data.get('title', final_title)
            break # Hanya perlu baris pertama untuk judul
        
        # --- PERBAIKAN: Tawarkan Pilihan Resolusi Cerdas ---
        parsed_formats = [
            {
                "id": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
                "text": "Video Kualitas Terbaik (Hingga 4K)"
            },
            {
                "id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                "text": "Video Kualitas Tinggi (Hingga 1080p)"
            },
            {
                "id": "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "text": "Video Kualitas Standar (Hingga 720p)"
            },
            {
                "id": "bestvideo[height<=480]+bestaudio/best[height<=480]",
                "text": "Video Kualitas Rendah (Hingga 480p)"
            },
            {
                "id": "bestaudio/best",
                "text": "Audio Saja (Format MP3)"
            }
        ]
        
        print(f"Menawarkan {len(parsed_formats)} pilihan format cerdas.")
        return {"status": "success", "title": final_title, "formats": parsed_formats}

    except subprocess.CalledProcessError as e:
        print(f"Error mengambil format: {e}")
        print(f"[yt-dlp] stdout:", e.stdout)
        print(f"[yt-dlp] stderr:", e.stderr)
        
        error_message = "Gagal mengambil format video."
        if "Sign in to confirm you're not a bot" in e.stderr:
            error_message = "Gagal: YouTube meminta verifikasi (cookie mungkin kedaluwarsa)."
        
        return {"status": "error", "message": error_message, "details": e.stderr}
    except Exception as e:
        print(f"Error tak terduga saat mengambil format: {e}")
        return {"status": "error", "message": "Error server internal saat parsing format.", "details": str(e)}


# --- ENDPOINT (Langkah 1) ---
@app.route('/api/get_formats', methods=['POST'])
def api_get_formats():
    data = request.get_json()
    media_url = data.get('url')
    if not media_url:
        return jsonify({"error": "URL tidak diberikan"}), 400

    # Lewati pilihan format untuk IG/TikTok/Pinterest
    if "instagram.com" in media_url or "tiktok.com" in media_url or "pinterest.com" in media_url:
        return jsonify({
            "status": "skip_format_selection",
            "message": "Platform ini langsung mengunduh tanpa pilihan format"
        })

    result = get_video_formats(media_url)
    
    if result["status"] == "error":
        return jsonify({"error": result["message"], "details": result.get("details", "")}), 500
    
    return jsonify(result)


# --- ENDPOINT (Langkah 2 / Alur Unduh) ---
@app.route('/api/download', methods=['POST'])
def download_media():
    data = request.get_json()
    media_url = data.get('url')
    download_format = data.get('format') 

    if not media_url or not download_format:
        return jsonify({"error": "URL atau format tidak diberikan"}), 400

    print(f"Menerima permintaan unduh untuk: {media_url} (Format: {download_format})")

    unique_id = str(uuid.uuid4())
    output_subdir = os.path.join(DOWNLOAD_DIR, unique_id)
    os.makedirs(output_subdir)
    
    return_filename = ""
    tool_used = ""
    result = None 
    
    try:
        command = []
        
        # --- KASUS 1: GALERI (Instagram, Pinterest, TikTok) ---
        if download_format == "gallery_dl_zip":
            print("Menggunakan gallery-dl (alur Zip)...")
            tool_used = "gallery-dl"
            command = [
                sys.executable, '-m', 'gallery_dl', # <-- PERBAIKAN: Gunakan sys.executable
                '--no-check-certificate',
                '--sleep', '2-4', 
                '--user-agent', USER_AGENT
            ]
            
            if "instagram.com" in media_url and os.path.exists(INSTAGRAM_COOKIES):
                command.extend(['--cookies', INSTAGRAM_COOKIES])
            if "tiktok.com" in media_url and os.path.exists(TIKTOK_COOKIES):
                command.extend(['--cookies', TIKTOK_COOKIES])

            command.extend(['-d', output_subdir, media_url])
        
        # --- KASUS 2: VIDEO (YouTube, Twitter) ---
        else:
            print(f"Menggunakan yt-dlp (format ID: {download_format})...")
            tool_used = "yt-dlp"
            # Template nama file yang lebih bersih
            output_template = os.path.join(output_subdir, '%(title)s - %(id)s.%(ext)s')
            
            command = [
                sys.executable, '-m', 'yt_dlp', # <-- PERBAIKAN: Gunakan sys.executable
                '--no-check-certificate',
                '--geo-bypass',
                '--no-playlist',
                '--user-agent', USER_AGENT,
                '-f', download_format,
                '-o', output_template,
                media_url
            ]
            
            if "twitter.com" in media_url or "x.com" in media_url:
                if os.path.exists(TWITTER_COOKIES):
                    command.extend(['--cookies', TWITTER_COOKIES])
            
            if "youtube.com" in media_url or "youtu.be" in media_url:
                if os.path.exists(YOUTUBE_COOKIES):
                    command.extend(['--cookies', YOUTUBE_COOKIES])
            
            # --- PERBAIKAN: Logika Audio vs Video yang Jelas ---
            if 'audio' in download_format.lower() or download_format == 'bestaudio/best':
                print("Mode: Audio Saja. Mengonversi ke MP3...")
                command.extend(['-x', '--audio-format', 'mp3'])
            else:
                print(f"Mode: Video. Memastikan container MP4 (Merge + Remux) untuk kompatibilitas...")
                command.extend(['--merge-output-format', 'mp4']) 
                command.extend(['--remux-video', 'mp4'])

        
        # --- Jalankan Perintah ---
        print(f"Akan menjalankan perintah: {' '.join(command)}")
        print(f"Proses unduhan dimulai (batas waktu: {DOWNLOAD_TIMEOUT} detik)...")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False, 
            encoding='utf-8',
            errors='replace', 
            timeout=DOWNLOAD_TIMEOUT
        )
        
        print("...Proses unduhan selesai.")
        print(f"[{tool_used}] stdout:", result.stdout)
        print(f"[{tool_used}] stderr:", result.stderr)
        
        # --- Logika Pemrosesan Hasil (Zipping & Pencarian Rekursif) ---
        print(f"Memeriksa hasil di: {output_subdir}")
        
        all_files = []
        for root, dirs, files in os.walk(output_subdir):
            for file in files:
                if file.endswith('.part'): continue
                full_path = os.path.join(root, file)
                all_files.append(full_path)
        
        all_files = [f for f in all_files if os.path.getsize(f) > 0]
        print(f"Total file valid ditemukan (rekursif, >0 byte): {len(all_files)}")

        # --- PERBAIKAN LOGIKA CAROUSEL ---
        media_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mkv', '.webm', '.mov']
        media_files = [
            f for f in all_files 
            if os.path.splitext(f)[1].lower() in media_extensions
        ]
        print(f"Ditemukan {len(media_files)} file media.")

        if not media_files:
            if result.returncode != 0:
                print(f"subprocess gagal DAN tidak ada file media yang ditemukan.")
                error_detail = result.stderr
                if "login required" in error_detail or "HTTP redirect to login page" in error_detail:
                    error_message = f"Gagal: {tool_used} memerlukan login (cookie mungkin kedaluwarsa)."
                elif "No video formats found" in error_detail:
                     error_message = "Gagal: Postingan ini (mungkin foto) tidak dapat diunduh."
                else:
                    error_message = f"Gagal menjalankan {tool_used}."
                return jsonify({"error": error_message, "details": error_detail}), 500
            else:
                raise Exception("Proses unduhan selesai tanpa error, tetapi tidak ada file media yang ditemukan.")
        
        elif len(media_files) > 1:
            print(f"Menemukan {len(media_files)} file media. Membuat file .zip...")
            zip_filename_no_ext = f"{unique_id}_gallery_{int(time.time())}"
            zip_base_path = os.path.join(DOWNLOAD_DIR, zip_filename_no_ext)
            
            shutil.make_archive(zip_base_path, 'zip', output_subdir)
            
            return_filename = f"{zip_filename_no_ext}.zip"
            message = f"Unduhan carousel/galeri berhasil ({len(media_files)} media di-zip)!"
            print(f"File Zip dibuat: {return_filename}")

        else:
            print("Menemukan 1 file media. Memindahkan ke direktori utama...")
            full_path = media_files[0]
            single_file_name = os.path.basename(full_path)
            
            safe_single_file_name = f"{unique_id}_{single_file_name}"
            dst_path = os.path.join(DOWNLOAD_DIR, safe_single_file_name)
            shutil.move(full_path, dst_path)
            
            return_filename = safe_single_file_name
            message = f"Unduhan berhasil ({tool_used})!"
            print(f"File dipindahkan: {return_filename}")

        download_link = f'/downloads/{return_filename}'
        return jsonify({
            "message": message,
            "download_url": download_link,
            "filename": return_filename
        })

    except subprocess.TimeoutExpired as e:
        print(f"Error: Proses unduhan melebihi batas waktu ({DOWNLOAD_TIMEOUT} detik).")
        return jsonify({"error": f"Proses unduhan terlalu lama (melebihi {DOWNLOAD_TIMEOUT} detik) dan dihentikan."}), 500
    except Exception as e:
        print(f"Terjadi error tak terduga: {e}")
        return jsonify({"error": "Terjadi error internal server.", "details": str(e)}), 500
    
    finally:
        if os.path.exists(output_subdir):
            try:
                shutil.rmtree(output_subdir)
                print(f"Membersihkan folder sementara: {output_subdir}")
            except Exception as cleanup_error:
                print(f"Warning: Gagal membersihkan folder sementara: {cleanup_error}")


# --- Endpoint untuk Menyajikan File ---
@app.route('/downloads/<path:filename>')
def serve_file(filename):
    if '..' in filename or filename.startswith('/'):
        return jsonify({"error": "Invalid filename"}), 400
    
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

# --- Jalankan Server ---
if __name__ == '__main__':
    write_cookies_from_env() 
    port = int(os.environ.get('PORT', SERVER_PORT)) 
    print(f"Menjalankan server di http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
