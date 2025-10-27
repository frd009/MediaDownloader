import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import shutil
import base64
import time # Diperlukan untuk Fix #10

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

# --- FIX 6: Perluas konfigurasi CORS untuk preflight OPTIONS ---
FRONTEND_DOMAIN = "https://mediadown.kesug.com" 

CORS(app, resources={
    r"/api/*": {
        "origins": FRONTEND_DOMAIN,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    },
    r"/downloads/*": {
        "origins": FRONTEND_DOMAIN,
        "methods": ["GET", "OPTIONS"], # Tambahkan OPTIONS
        "allow_headers": ["Content-Type"]
    }
})
# --- AKHIR FIX 6 ---

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- FUNGSI HELPER: Mengambil Format Video (Langkah 1) ---
def get_video_formats(media_url):
    print(f"Mengambil format untuk: {media_url}")
    
    command = [
        'python', '-m', 'yt_dlp',
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
            errors='replace',  # FIX 7: Tambahkan error handling
            timeout=60
        )
        
        # Inisialisasi daftar format
        parsed_formats = []
        final_title = "Judul Tidak Diketahui"
        
        # yt-dlp -j dapat mengeluarkan beberapa JSON (satu per video di playlist)
        # Kita hanya ambil yang pertama.
        for line in result.stdout.strip().split('\n'):
            data = json.loads(line)
            final_title = data.get('title', final_title)
            
            # --- FIX 5: Perbarui logika format YouTube ---
            parsed_formats = [
                {
                    # Coba 1080p (web/mp4) + audio terbaik, fallback ke 720p
                    "id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                    "text": "Video Kualitas Terbaik (Hingga 1080p)"
                },
                {
                    # Opsi fallback aman
                    "id": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]",
                    "text": "Video Kompatibel (Hingga 720p, MP4)"
                },
                {
                    "id": "bestaudio/best",
                    "text": "Audio Saja (Unduh terbaik, konversi ke MP3)"
                }
            ]
            # --- AKHIR FIX 5 ---
            
            # Hentikan loop setelah data JSON pertama diproses
            break 
        
        if not parsed_formats:
             print("Tidak ada format video/audio yang ditemukan.")
             return {"status": "error", "message": "Tidak ada format video/audio yang ditemukan."}
        
        print(f"Menemukan {len(parsed_formats)} format yang relevan.")
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

    # --- FIX 1 & 2: Skip format selection untuk gallery-dl targets ---
    if "instagram.com" in media_url or "tiktok.com" in media_url or "pinterest.com" in media_url:
        return jsonify({
            "status": "skip_format_selection",
            "message": "Platform ini langsung mengunduh tanpa pilihan format"
        })
    # --- AKHIR FIX 1 & 2 ---

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
    result = None # Inisialisasi result
    
    try:
        command = []
        
        # --- KASUS 1: GALERI (Instagram, Pinterest, TikTok) ---
        if download_format == "gallery_dl_zip":
            print("Menggunakan gallery-dl (alur Zip)...")
            tool_used = "gallery-dl"
            command = [
                'python', '-m', 'gallery_dl',
                '--no-check-certificate',
                '--sleep', '2-4', # Tambahkan jeda
                '--user-agent', USER_AGENT
            ]
            
            # Tambahkan cookie jika ada
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
                'python', '-m', 'yt_dlp',
                '--no-check-certificate',
                '--geo-bypass',
                '--no-playlist',
                '--user-agent', USER_AGENT,
                '-f', download_format,
                '--merge-output-format', 'mp4', # Gabungkan ke MP4
                '-o', output_template,
                media_url
            ]
            
            if "twitter.com" in media_url or "x.com" in media_url:
                if os.path.exists(TWITTER_COOKIES):
                    command.extend(['--cookies', TWITTER_COOKIES])
            
            if "youtube.com" in media_url or "youtu.be" in media_url:
                if os.path.exists(YOUTUBE_COOKIES):
                    command.extend(['--cookies', YOUTUBE_COOKIES])
            
            # --- FIX 3: Perbaiki logika deteksi audio ---
            if 'audio' in download_format.lower() or download_format == 'bestaudio/best':
                 command.extend(['-x', '--audio-format', 'mp3'])
            # --- AKHIR FIX 3 ---

        
        # --- Jalankan Perintah ---
        print(f"Akan menjalankan perintah: {' '.join(command)}")
        print(f"Proses unduhan dimulai (batas waktu: {DOWNLOAD_TIMEOUT} detik)...")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False, # Jangan crash jika return code != 0
            encoding='utf-8',
            errors='replace', # FIX 7: Tambahkan error handling
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
        
        # --- FIX 8: Filter file 0-byte ---
        all_files = [f for f in all_files if os.path.getsize(f) > 0]
        print(f"Total file valid ditemukan (rekursif, >0 byte): {len(all_files)}")
        # --- AKHIR FIX 8 ---

        if not all_files:
            # Jika tidak ada file, cek return code
            if result.returncode != 0:
                print(f"subprocess gagal DAN tidak ada file yang ditemukan.")
                error_detail = result.stderr
                if "login required" in error_detail or "HTTP redirect to login page" in error_detail:
                    error_message = f"Gagal: {tool_used} memerlukan login (cookie mungkin kedaluwarsa)."
                elif "No video formats found" in error_detail:
                     error_message = "Gagal: Postingan ini (mungkin foto) tidak dapat diunduh."
                else:
                    error_message = f"Gagal menjalankan {tool_used}."
                return jsonify({"error": error_message, "details": error_detail}), 500
            else:
                 # Sukses tapi 0 file (kasus aneh)
                raise Exception("Proses unduhan selesai tanpa error, tetapi tidak ada file yang ditemukan.")
        
        # --- PERBAIKAN BUG CAROUSEL ---
        # Hapus 'or tool_used == "gallery-dl"' agar foto tunggal tidak di-zip
        elif len(all_files) > 1:
        # --- AKHIR PERBAIKAN ---
            print(f"Menemukan {len(all_files)} file. Membuat file .zip...")
            # --- FIX 10: Tambahkan timestamp ke zip ---
            zip_filename_no_ext = f"{unique_id}_gallery_{int(time.time())}"
            # --- AKHIR FIX 10 ---
            zip_base_path = os.path.join(DOWNLOAD_DIR, zip_filename_no_ext)
            
            shutil.make_archive(zip_base_path, 'zip', output_subdir)
            
            return_filename = f"{zip_filename_no_ext}.zip"
            message = f"Unduhan carousel/galeri berhasil ({len(all_files)} file di-zip)!"
            print(f"File Zip dibuat: {return_filename}")

        else:
            print("Menemukan 1 file. Memindahkan ke direktori utama...")
            full_path = all_files[0]
            single_file_name = os.path.basename(full_path)
            # Pastikan nama file aman untuk dipindahkan
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
    
    # --- FIX 4: Perbaiki logika cleanup ---
    finally:
        if os.path.exists(output_subdir):
            try:
                shutil.rmtree(output_subdir)
                print(f"Membersihkan folder sementara: {output_subdir}")
            except Exception as cleanup_error:
                print(f"Warning: Gagal membersihkan folder sementara: {cleanup_error}")
    # --- AKHIR FIX 4 ---

# --- Endpoint untuk Menyajikan File ---
@app.route('/downloads/<path:filename>')
def serve_file(filename):
    # --- FIX 9: Cegah path traversal ---
    if '..' in filename or filename.startswith('/'):
        return jsonify({"error": "Invalid filename"}), 400
    # --- AKHIR FIX 9 ---
    
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)
# --- AKHIR FIX 9 (Fungsi) ---

# --- Jalankan Server ---
if __name__ == '__main__':
    # Jalankan fungsi untuk menulis cookie dari env saat server mulai
    write_cookies_from_env() 
    
    port = int(os.environ.get('PORT', SERVER_PORT)) 
    
    print(f"Menjalankan server di http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
