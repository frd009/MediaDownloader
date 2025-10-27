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
YOUTUBE_COOKIES = "youtube_cookies.txt"

# --- PERBAIKAN: Tambahkan User-Agent Browser ---
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'

# --- PERSIAPAN DEPLOYMENT: Tulis Cookies dari Environment Variables ---
def write_cookies_from_env():
    print("Memeriksa environment variables untuk cookies...")
    
    insta_cookie_data_b64 = os.environ.get('INSTA_COOKIE_B64_DATA')
    twitter_cookie_data_b64 = os.environ.get('TWITTER_COOKIE_B64_DATA')
    tiktok_cookie_data_b64 = os.environ.get('TIKTOK_COOKIE_B64_DATA')
    youtube_cookie_data_b64 = os.environ.get('YOUTUBE_COOKIE_B64_DATA')

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

        if youtube_cookie_data_b64:
            with open(YOUTUBE_COOKIES, 'wb') as f:
                f.write(base64.b64decode(youtube_cookie_data_b64))
            print(f"Berhasil menulis {YOUTUBE_COOKIES} dari env variable Base64.")
        else:
            print(f"Peringatan: YOUTUBE_COOKIE_B64_DATA env variable tidak ditemukan.")
            
    except Exception as e:
        print(f"ERROR: Gagal mendekode atau menulis file cookie dari Base64. {e}")
        print("Pastikan Anda menyalin string Base64 yang BENAR ke environment variables.")

# --- Akhir Persiapan Deployment ---


app = Flask(__name__)

# --- KONFIGURASI CORS SPESIFIK UNTUK INFINITYFREE ---
FRONTEND_DOMAIN = "https://mediadown.kesug.com" 

CORS(app, resources={
    r"/api/*": {"origins": FRONTEND_DOMAIN},
    r"/downloads/*": {"origins": FRONTEND_DOMAIN}
})
# --- AKHIR KONFIGURASI CORS ---


if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- FUNGSI HELPER BARU: Mengambil Format Video (Langkah 1) ---
def get_video_formats(media_url):
    """
    Menjalankan yt-dlp -j untuk mendapatkan daftar format JSON.
    HANYA UNTUK YT/TWITTER. Instagram/TikTok dilewati.
    """
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
        else:
            print("Peringatan: File cookie Twitter tidak ditemukan.")
    
    if "youtube.com" in media_url or "youtu.be" in media_url:
        print("Mendeteksi URL YouTube, menambahkan file cookie...")
        if os.path.exists(YOUTUBE_COOKIES):
            command.extend(['--cookies', YOUTUBE_COOKIES])
        else:
            print("Peringatan: File cookie YouTube tidak ditemukan.")
            
    # Instagram tidak lagi mengambil format, dilewati oleh frontend
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            timeout=60
        )
        
        parsed_formats = []
        final_title = 'Judul Tidak Diketahui'
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
                
            data = json.loads(line)
            final_title = data.get('title', final_title)
            formats = data.get('formats', [])

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
        
        if not unique_formats:
             print("Tidak ada format video/audio yang ditemukan.")
             return {"status": "success", "title": final_title, "formats": [{"id": "best", "text": "Unduh Kualitas Terbaik (Jika ada)"}]}
        
        print(f"Menemukan {len(unique_formats)} format yang relevan.")
        return {"status": "success", "title": final_title, "formats": unique_formats}

    except subprocess.CalledProcessError as e:
        print(f"Error mengambil format: {e}")
        print(f"[yt-dlp] stdout:", e.stdout)
        print(f"[yt-dlp] stderr:", e.stderr)
        
        error_details = e.stderr
        
        if 'Sign in to confirm' in error_details:
            error_details = "Gagal: YouTube meminta verifikasi (Sign in to confirm you're not a bot). Ini biasanya karena cookie YouTube tidak ada, tidak valid, atau kedaluwarsa. Harap perbarui cookie Anda."
        if 'HTTP redirect to login page' in error_details:
             error_details = "Gagal: Instagram mengalihkan ke halaman login. Ini 100% berarti cookie Instagram Anda tidak valid atau kedaluwarsa. Harap perbarui."

        return {"status": "error", "message": "Gagal mengambil format video.", "details": error_details}

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
        
        # --- PERBAIKAN LOGIKA: KEMBALIKAN INSTAGRAM KE GALLERY-DL ---
        
        # KASUS 1: GALLERY-DL (Untuk Instagram, Pinterest, TikTok)
        # Frontend mengirim 'gallery_dl_zip' untuk IG, TikTok, Pinterest.
        if download_format == "gallery_dl_zip":
            print("Menggunakan gallery-dl (alur Zip untuk IG/TikTok/Pinterest)...")
            tool_used = "gallery-dl"
            command = [
                'python', '-m', 'gallery_dl',
                '--no-check-certificate',
                '--sleep', '2-4',  
                '--user-agent', USER_AGENT, 
            ]
            
            # Tambahkan cookie yang relevan
            if "instagram.com" in media_url:
                print("Mendeteksi URL Instagram, menambahkan file cookie...")
                if os.path.exists(INSTAGRAM_COOKIES):
                    command.extend(['--cookies', INSTAGRAM_COOKIES])
                else:
                    print("Peringatan: File cookie Instagram tidak ditemukan.")

            if "tiktok.com" in media_url:
                print("Mendeteksi URL TikTok, menambahkan file cookie...")
                if os.path.exists(TIKTOK_COOKIES):
                    command.extend(['--cookies', TIKTOK_COOKIES])

            command.extend(['-d', output_subdir, media_url])
        
        # KASUS 2: YT-DLP (Untuk YouTube, Twitter, dll)
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
            
            if "youtube.com" in media_url or "youtu.be" in media_url:
                print("Mendeteksi URL YouTube, menambahkan file cookie...")
                if os.path.exists(YOUTUBE_COOKIES):
                    command.extend(['--cookies', YOUTUBE_COOKIES])
                else:
                    print("Peringatan: File cookie YouTube tidak ditemukan.")
            
            if 'mp3' in download_format or 'audio' in download_format.lower():
                 command.extend(['-x', '--audio-format', 'mp3'])

        
        # --- Jalankan Perintah ---
        print(f"Akan menjalankan perintah: {' '.join(command)}")
        print(f"Proses unduhan dimulai (batas waktu: {DOWNLOAD_TIMEOUT} detik)...")
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False, # <-- Tetap False, ini penting
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

        # --- Logika pengecekan file ---
        if not all_files:
            # Jika tidak ada file, periksa apakah subprocess GAGAL.
            if result.returncode != 0:
                print("subprocess gagal DAN tidak ada file yang ditemukan.")
                # Lempar error agar ditangkap 'except' block
                raise subprocess.CalledProcessError(
                    result.returncode, 
                    command, 
                    output=result.stdout, 
                    stderr=result.stderr
                )
            else:
                # Subprocess sukses (returncode 0) tapi tidak ada file? Aneh.
                raise Exception("Proses unduhan berhasil tetapi tidak ada file yang ditemukan.")
        
        # --- Jika kita sampai di sini, all_files TIDAK kosong ---
        
        elif len(all_files) > 1:
            print(f"Menemukan {len(all_files)} file. Membuat file .zip...")
            zip_filename_no_ext = f"{unique_id}_gallery"
            zip_base_path = os.path.join(DOWNLOAD_DIR, zip_filename_no_ext)
            
            shutil.make_archive(zip_base_path, 'zip', output_subdir)
            
            return_filename = f"{zip_filename_no_ext}.zip"
            message = f"Unduhan galeri/carousel berhasil ({len(all_files)} file di-zip)!"
            print(f"File Zip dibuat: {return_filename}")

        else:
            print("Menemukan 1 file. Memindahkan ke direktori utama...")
            full_path = all_files[0]
            single_file_name = os.path.basename(full_path)
            dst_path = os.path.join(DOWNLOAD_DIR, single_file_name)
            
            if os.path.exists(dst_path):
                name, ext = os.path.splitext(single_file_name)
                single_file_name = f"{name}-{unique_id}{ext}"
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
        
        error_details = e.stderr
        if '429 Too Many Requests' in error_details:
             error_details = "Gagal: Instagram memblokir permintaan karena terlalu sering (429 Too Many Requests). Ini biasanya karena cookie yang tidak valid atau kedaluwarsa. Harap perbarui cookie Anda di environment variables."
        elif 'login required' in error_details.lower() or 'redirect to login page' in error_details:
             error_details = "Gagal: Instagram/TikTok memerlukan login. Ini 100% berarti cookie Anda tidak valid atau kedaluwarsa. Harap perbarui."
        elif 'Sign in to confirm' in error_details:
             error_details = "Gagal: YouTube meminta verifikasi (Sign in to confirm you're not a bot). Ini biasanya karena cookie YouTube tidak ada, tidak valid, atau kedaluwarsa. Harap perbarui cookie Anda."
        elif 'Signature extraction failed' in error_details:
             error_details = "Gagal: YouTube Signature extraction failed. Server sedang memperbarui yt-dlp, silakan coba lagi dalam 1 menit."
        elif "No video formats found!" in error_details and "instagram.com" in media_url:
            error_details = "Gagal: yt-dlp melaporkan 'No video formats found'. Ini terjadi karena postingan tersebut adalah FOTO, dan logikanya salah."

        return jsonify({"error": f"Gagal mengunduh media dengan {tool_used}.", "details": error_details}), 500
    except Exception as e:
        print(f"Terjadi error tak terduga: {e}")
        return jsonify({"error": f"Terjadi error internal server: {str(e)}"}), 500
    
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
