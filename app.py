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

# --- Konfigurasi CORS ---
# (Memperbolehkan frontend Anda untuk mengakses)
FRONTEND_DOMAIN = "https://mediadown.kesug.com" 

CORS(app, resources={
    r"/api/*": {
        "origins": FRONTEND_DOMAIN,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    },
    r"/downloads/*": {
        "origins": FRONTEND_DOMAIN,
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
            errors='replace',  
            timeout=60
        )
        
        parsed_formats = []
        final_title = "Judul Tidak Diketahui"
        
        # Iterasi melalui setiap baris output JSON (meskipun --no-playlist, beberapa link menghasilkan >1)
        for line in result.stdout.strip().split('\n'):
            try:
                data = json.loads(line)
                final_title = data.get('title', final_title)
                
                # --- PERBAIKAN LOGIKA FORMAT (Suara & Resolusi) ---
                if data.get('formats'):
                    print("Memindai format video...")
                    for f in data['formats']:
                        # Kita hanya ingin format yang SUDAH memiliki video DAN audio
                        # Acodec 'none' berarti tidak ada audio. Vcodec 'none' berarti tidak ada video.
                        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                            # Coba dapatkan resolusi dan ukuran file
                            height = f.get('height')
                            filesize_approx = f.get('filesize_approx') or f.get('filesize')
                            
                            # Buat teks deskripsi
                            text = f.get('format_note', f.get('format_id', 'Format tidak diketahui'))
                            if height:
                                text = f"{height}p"
                                
                            if filesize_approx:
                                size_mb = filesize_approx / (1024 * 1024)
                                text += f" (~{size_mb:.1f} MB)"
                            
                            parsed_formats.append({
                                "id": f['format_id'],
                                "text": text
                            })
                
                # Opsi Audio Saja (Selalu tawarkan ini sebagai fallback)
                parsed_formats.append({
                    "id": "bestaudio/best",
                    "text": "Audio Saja (Unduh terbaik, konversi ke MP3)"
                })
                # --- AKHIR PERBAIKAN ---

                # Hanya proses data JSON pertama yang valid
                break 
            
            except json.JSONDecodeError:
                print(f"Peringatan: Melewatkan baris output non-JSON: {line}")
                continue
        
        if not parsed_formats:
             print("Tidak ada format V+A yang ditemukan. Menawarkan fallback.")
             # Fallback jika tidak ada format V+A (video terpisah)
             parsed_formats = [
                {
                    "id": "bestvideo+bestaudio/best",
                    "text": "Video Terbaik (Pisah, digabung)"
                },
                {
                    "id": "bestaudio/best",
                    "text": "Audio Saja (MP3)"
                }
            ]

        # Hapus duplikat (terutama untuk 'Audio Saja')
        unique_formats = []
        seen_ids = set()
        for f in parsed_formats:
            if f['id'] not in seen_ids:
                unique_formats.append(f)
                seen_ids.add(f['id'])
        
        print(f"Menemukan {len(unique_formats)} format yang relevan.")
        return {"status": "success", "title": final_title, "formats": unique_formats}

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

    # Lewati pemilihan format untuk platform galeri
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
                '--sleep', '2-4', 
                '--user-agent', USER_AGENT,
                '--write-metadata', # Minta metadata (untuk file .txt)
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
            output_template = os.path.join(output_subdir, '%(title)s - %(id)s.%(ext)s')
            
            command = [
                'python', '-m', 'yt_dlp',
                '--no-check-certificate',
                '--geo-bypass',
                '--no-playlist',
                '--user-agent', USER_AGENT,
                '-f', download_format,
                '-o', output_template,
                media_url
            ]
            
            # KASUS A: Format HANYA AUDIO
            if 'audio' in download_format.lower() and 'video' not in download_format.lower():
                print("Mendeteksi format audio, menambahkan -x --audio-format mp3")
                command.extend(['-x', '--audio-format', 'mp3'])
            
            # KASUS B: Format VIDEO (atau Video+Audio, atau fallback merge)
            else:
                # --- PERBAIKAN ERROR 0xc00d36e6 ---
                # Paksa remux ke MP4 container. Ini memperbaiki 0xc00d36e6 di Windows
                print("Mendeteksi format video. Memaksa remux ke MP4 untuk kompatibilitas.")
                command.extend(['--remux-video', 'mp4'])
                # --- AKHIR PERBAIKAN ---
            
            if "twitter.com" in media_url or "x.com" in media_url:
                if os.path.exists(TWITTER_COOKIES):
                    command.extend(['--cookies', TWITTER_COOKIES])
            
            if "youtube.com" in media_url or "youtu.be" in media_url:
                if os.path.exists(YOUTUBE_COOKIES):
                    command.extend(['--cookies', YOUTUBE_COOKIES])

        
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
        
        # --- Logika Pemrosesan Hasil ---
        print(f"Memeriksa hasil di: {output_subdir}")
        
        all_files = []
        for root, dirs, files in os.walk(output_subdir):
            for file in files:
                # Abaikan file parsial atau file tersembunyi
                if file.endswith('.part') or file.startswith('.'): continue
                full_path = os.path.join(root, file)
                all_files.append(full_path)
        
        # Filter file 0-byte
        all_files = [f for f in all_files if os.path.getsize(f) > 0]
        print(f"Total file valid ditemukan (rekursif, >0 byte): {len(all_files)}")

        # --- PERBAIKAN MASALAH CAROUSEL (Mulai) ---
        # Definisikan ekstensi media untuk membedakan dari file .txt/.json
        MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mov', '.mkv', '.avi')
        
        media_files = [f for f in all_files if f.lower().endswith(MEDIA_EXTENSIONS)]
        print(f"Menemukan {len(media_files)} file media.")

        if not media_files:
            # Jika tidak ada file media, cek return code
            if result.returncode != 0:
                print(f"subprocess gagal DAN tidak ada file media yang ditemukan.")
                error_detail = result.stderr
                if "login required" in error_detail or "HTTP redirect to login page" in error_detail:
                    error_message = f"Gagal: {tool_used} memerlukan login (cookie mungkin kedaluwarsa)."
                elif "No video formats found" in error_detail or "No media found" in error_detail:
                     error_message = "Gagal: Postingan ini (mungkin text-only) tidak dapat diunduh."
                else:
                    error_message = f"Gagal menjalankan {tool_used}."
                return jsonify({"error": error_message, "details": error_detail}), 500
            else:
                 # Sukses tapi 0 file (kasus aneh)
                raise Exception("Proses unduhan selesai tanpa error, tetapi tidak ada file media yang ditemukan.")
        
        # KASUS 1: LEBIH DARI 1 FILE MEDIA (Carousel/Galeri) -> BUAT ZIP
        elif len(media_files) > 1:
            print(f"Menemukan {len(media_files)} file media. Membuat file .zip...")
            zip_filename_no_ext = f"{unique_id}_gallery_{int(time.time())}"
            zip_base_path = os.path.join(DOWNLOAD_DIR, zip_filename_no_ext)
            
            # Kita zip seluruh direktori (termasuk .txt jika ada)
            shutil.make_archive(zip_base_path, 'zip', output_subdir)
            
            return_filename = f"{zip_filename_no_ext}.zip"
            message = f"Unduhan carousel/galeri berhasil ({len(media_files)} media di-zip)!"
            print(f"File Zip dibuat: {return_filename}")

        # KASUS 2: HANYA 1 FILE MEDIA (Foto/Video Tunggal) -> JANGAN DI-ZIP
        else: # (len(media_files) == 1)
            print("Menemukan 1 file media. Memindahkan ke direktori utama (mengabaikan file .txt)...")
            full_path = media_files[0] # Ambil satu-satunya file media
            single_file_name = os.path.basename(full_path)
            # Pastikan nama file aman untuk dipindahkan
            safe_single_file_name = f"{unique_id}_{single_file_name}"
            dst_path = os.path.join(DOWNLOAD_DIR, safe_single_file_name)
            
            shutil.move(full_path, dst_path)
            
            return_filename = safe_single_file_name
            message = f"Unduhan berhasil ({tool_used})!"
            print(f"File dipindahkan: {return_filename}")
        
        # --- PERBAIKAN MASALAH CAROUSEL (Selesai) ---


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
        # Selalu bersihkan folder sementara
        if os.path.exists(output_subdir):
            try:
                shutil.rmtree(output_subdir)
                print(f"Membersihkan folder sementara: {output_subdir}")
            except Exception as cleanup_error:
                print(f"Warning: Gagal membersihkan folder sementara: {cleanup_error}")


# --- Endpoint untuk Menyajikan File ---
@app.route('/downloads/<path:filename>')
def serve_file(filename):
    # Cegah path traversal
    if '..' in filename or filename.startswith('/'):
        return jsonify({"error": "Invalid filename"}), 400
    
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

# --- Jalankan Server ---
if __name__ == '__main__':
    write_cookies_from_env() 
    port = int(os.environ.get('PORT', SERVER_PORT)) 
    
    print(f"Menjalankan server di http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
