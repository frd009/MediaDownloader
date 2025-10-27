import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import shutil
import base64

# --- Konfigurasi ---
DOWNLOAD_DIR = "downloaded_videos"
SERVER_PORT = 5000
DOWNLOAD_TIMEOUT = 300  # 5 menit

INSTAGRAM_COOKIES = "instagram_cookies.txt"
TWITTER_COOKIES = "twitter_cookies.txt" 
TIKTOK_COOKIES = "tiktok_cookies.txt" 

# --- PERSIAPAN DEPLOYMENT: Tulis Cookies dari Environment Variables ---
def write_cookies_from_env():
    print("Memeriksa environment variables untuk cookies...")
    
    insta_cookie_data_b64 = os.environ.get('INSTA_COOKIE_B64_DATA')
    twitter_cookie_data_b64 = os.environ.get('TWITTER_COOKIE_B64_DATA')
    tiktok_cookie_data_b64 = os.environ.get('TIKTOK_COOKIE_B64_DATA')

    try:
        if insta_cookie_data_b64:
            with open(INSTAGRAM_COOKIES, 'wb') as f:
                f.write(base64.b64decode(insta_cookie_data_b64))
            print(f"Berhasil menulis {INSTAGRAM_COOKIES} dari env variable Base64.")
        else:
            print(f"Peringatan: INSTA_COOKIE_B64_DATA env variable tidak ditemukan.")
            
        if twitter_cookie_data_b64:
            with open(TWITTER_COOKIES, 'wb') as f:
                f.write(base64.b64decode(twitter_cookie_data_b64))
            print(f"Berhasil menulis {TWITTER_COOKIES} dari env variable Base64.")
        else:
            print(f"Peringatan: TWITTER_COOKIE_B64_DATA env variable tidak ditemukan.")

        if tiktok_cookie_data_b64:
            with open(TIKTOK_COOKIES, 'wb') as f:
                f.write(base64.b64decode(tiktok_cookie_data_b64))
            print(f"Berhasil menulis {TIKTOK_COOKIES} dari env variable Base64.")
        else:
            print(f"Peringatan: TIKTOK_COOKIE_B64_DATA env variable tidak ditemukan.")
            
    except Exception as e:
        print(f"ERROR: Gagal mendekode atau menulis file cookie dari Base64. {e}")
        print("Pastikan Anda menyalin string Base64 yang BENAR ke environment variables.")

# --- Akhir Persiapan Deployment ---


app = Flask(__name__)

# --- PERBAIKAN: KONFIGURASI CORS SPESIFIK UNTUK INFINITYFREE ---
# Baris 'CORS(app)' dihapus dan diganti dengan ini:
FRONTEND_DOMAIN = "https://mediadown.kesug.com" 

CORS(app, resources={
    r"/api/*": {"origins": FRONTEND_DOMAIN},
    r"/downloads/*": {"origins": FRONTEND_DOMAIN}
})
# --- AKHIR PERBAIKAN CORS ---


if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- FUNGSI HELPER BARU: Mengambil Format Video (Langkah 1) ---
def get_video_formats(media_url):
    """
    Menjalankan yt-dlp -j untuk mendapatkan daftar format JSON.
    """
    print(f"Mengambil format untuk: {media_url}")
    
    command = [
        'python', '-m', 'yt_dlp',
        '-j', 
        '--no-check-certificate',
        '--geo-bypass',
        '--no-playlist',
        media_url
    ]
    
    if "twitter.com" in media_url or "x.com" in media_url:
        print("Mendeteksi URL Twitter/X, menambahkan file cookie...")
        if os.path.exists(TWITTER_COOKIES):
            command.extend(['--cookies', TWITTER_COOKIES])
        else:
            print("Peringatan: File cookie Twitter tidak ditemukan.")
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            timeout=60
        )
        
        data = json.loads(result.stdout)
        title = data.get('title', 'Judul Tidak Diketahui')
        formats = data.get('formats', [])
        
        parsed_formats = []
        
        for f in formats:
            format_id = f.get('format_id')
            ext = f.get('ext')
            height = f.get('height')
            format_note = f.get('format_note')
            
            if not format_note:
                if height:
                    format_note = f"{height}p"
                else:
                    format_note = "Audio"

            abr = f.get('abr')
            audio_note = f" ({abr}k)" if abr else ""
            
            if (f.get('vcodec') != 'none' and f.get('acodec') != 'none' and height and height <= 1080):
                parsed_formats.append({
                    "id": format_id,
                    "text": f"Video {format_note} ({ext}){audio_note} [Tergabung]"
                })
            elif (f.get('vcodec') != 'none' and f.get('acodec') == 'none' and height and height <= 1080):
                 parsed_formats.append({
                    "id": f"{format_id}+bestaudio", 
                    "text": f"Video {format_note} ({ext}) + Audio Terbaik [Gabung]"
                })
            elif (f.get('vcodec') == 'none' and f.get('acodec') != 'none' and ext in ['m4a', 'mp3', 'opus']):
                 parsed_formats.append({
                    "id": format_id,
                    "text": f"Audio Saja {format_note} ({ext}){audio_note}"
                })

        unique_formats = list({f['text']: f for f in parsed_formats}.values())
        
        print(f"Menemukan {len(unique_formats)} format yang relevan.")
        return {"status": "success", "title": title, "formats": unique_formats}

    except subprocess.CalledProcessError as e:
        print(f"Error mengambil format: {e}")
        print(f"[yt-dlp] stdout:", e.stdout)
        print(f"[yt-dlp] stderr:", e.stderr)
        return {"status": "error", "message": "Gagal mengambil format video.", "details": e.stderr}
    except Exception as e:
        print(f"Error tak terduga saat mengambil format: {e}")
        return {"status": "error", "message": "Error server internal saat parsing format.", "details": str(e)}


# --- ENDPOINT BARU (Langkah 1) ---
@app.route('/api/get_formats', methods=['POST'])
def api_get_formats():
    data = request.get_json()
    media_url = data.get('url')
    if not media_url:
        return jsonify({"error": "URL tidak diberikan"}), 400

    result = get_video_formats(media_url)
    
    if result["status"] == "error":
        return jsonify({"error": result["message"], "details": result.get("details", "")}), 500
    
    return jsonify(result)


# --- ENDPOINT DIPERBARUI (Langkah 2 / Alur Lama) ---
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
    
    try:
        command = []
        
        # --- KASUS 1: GALERI (Instagram, Pinterest, TikTok) ---
        if download_format == "gallery_dl_zip":
            print("Menggunakan gallery-dl (alur Zip)...")
            tool_used = "gallery-dl"
            command = [
                'python', '-m', 'gallery_dl',
                '--no-check-certificate'
            ]
            
            # Tambahkan cookie jika ada
            if os.path.exists(INSTAGRAM_COOKIES):
                command.extend(['--cookies', INSTAGRAM_COOKIES])
            if os.path.exists(TIKTOK_COOKIES):
                command.extend(['--cookies', TIKTOK_COOKIES])

            command.extend(['-d', output_subdir, media_url])
        
        # --- KASUS 2: VIDEO (YouTube, Twitter) ---
        else:
            print(f"Menggunakan yt-dlp (format ID: {download_format})...")
            tool_used = "yt-dlp"
            output_template = os.path.join(output_subdir, '%(title)s.%(ext)s')
            
            command = [
                'python', '-m', 'yt_dlp',
                '--no-check-certificate',
                '--geo-bypass',
                '--no-playlist',
                '-f', download_format, 
                '--merge-output-format', 'mp4',
                '-o', output_template,
                media_url
            ]
            
            if "twitter.com" in media_url or "x.com" in media_url:
                print("Mendeteksi URL Twitter/X, menambahkan file cookie...")
                if os.path.exists(TWITTER_COOKIES):
                    command.extend(['--cookies', TWITTER_COOKIES])
                else:
                    print("Peringatan: File cookie Twitter tidak ditemukan.")
            
            if 'mp3' in download_format or 'audio' in download_format.lower():
                 command.extend(['-x', '--audio-format', 'mp3'])

        
        # --- Jalankan Perintah ---
        print(f"Akan menjalankan perintah: {' '.join(command)}")
        print(f"Proses unduhan dimulai (batas waktu: {DOWNLOAD_TIMEOUT} detik)...")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
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
                all_files.append(os.path.join(root, file))
        
        print(f"Total file ditemukan (secara rekursif): {len(all_files)}")

        if not all_files:
            raise Exception("File diunduh tetapi tidak dapat ditemukan oleh server.")
        
        elif len(all_files) > 1:
            print(f"Menemukan {len(all_files)} file. Membuat file .zip...")
            zip_filename_no_ext = f"{unique_id}_gallery"
            zip_base_path = os.path.join(DOWNLOAD_DIR, zip_filename_no_ext)
            
            shutil.make_archive(zip_base_path, 'zip', output_subdir)
            
            return_filename = f"{zip_filename_no_ext}.zip"
            message = f"Unduhan carousel/galeri berhasil ({len(all_files)} file di-zip)!"
            print(f"File Zip dibuat: {return_filename}")

        else:
            print("Menemukan 1 file. Memindahkan ke direktori utama...")
            full_path = all_files[0]
            single_file_name = os.path.basename(full_path)
            dst_path = os.path.join(DOWNLOAD_DIR, single_file_name)
            shutil.move(full_path, dst_path)
            
            return_filename = single_file_name
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
    except subprocess.CalledProcessError as e:
        print(f"Error menjalankan {tool_used}: {e}")
        print(f"[{tool_used}] stdout:", e.stdout)
        print(f"[{tool_used}] stderr:", e.stderr)
        return jsonify({"error": f"Gagal mengunduh media dengan {tool_used}.", "details": e.stderr}), 500
    except Exception as e:
        print(f"Terjadi error tak terduga: {e}")
        return jsonify({"error": "Terjadi error internal server."}), 500
    
    finally:
        if os.path.exists(output_subdir):
            shutil.rmtree(output_subdir)
            print(f"Membersihkan folder sementara: {output_subdir}")

# --- Endpoint untuk Menyajikan File ---
@app.route('/downloads/<path:filename>')
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)

# --- Jalankan Server ---
if __name__ == '__main__':
    # Jalankan fungsi untuk menulis cookie dari env saat server mulai
    write_cookies_from_env() 
    
    # Port akan diambil dari env variable PORT di Railway, 
    # atau default ke 5000 jika dijalankan lokal
    port = int(os.environ.get('PORT', SERVER_PORT)) 
    
    print(f"Menjalankan server di http://0.0.0.0:{port}")
    # Host harus '0.0.0.0' untuk bisa diakses di Railway
    app.run(host='0.0.0.0', port=port, debug=False) # Debug mode harus False di produksi
