from flask import Flask, request, jsonify
import requests
import json
import threading
import asyncio
import aiohttp
from byte import Encrypt_ID, encrypt_api
from datetime import datetime, timedelta
import os # Dùng để kiểm tra file tồn tại

app = Flask(__name__)

# --- Cấu hình file ---
ACCOUNTS_FILE = 'accounts.json'
TOKENS_FILE = 'tokens.json'
TOKEN_LIFETIME_HOURS = 8 # Thời gian token còn hiệu lực (8 tiếng)

# --- 1. Quản lý tài khoản (Giữ nguyên) ---
def load_accounts():
    """Tải UID và mật khẩu từ accounts.json."""
    try:
        with open(ACCOUNTS_FILE, 'r') as file:
            accounts_list = json.load(file)
        accounts_dict = {
            account['uid']: account['password']
            for account in accounts_list if account.get('uid') and account.get('password')
        }
        print(f"Loaded {len(accounts_dict)} accounts.")
        return accounts_dict
    except FileNotFoundError:
        print(f"File {ACCOUNTS_FILE} not found.")
        return {}
    except Exception as e:
        print(f"Error loading accounts: {e}")
        return {}

# --- 2. Quản lý Token File ---

def load_tokens():
    """Tải token từ file nếu còn hiệu lực (chưa quá 8 giờ)."""
    if not os.path.exists(TOKENS_FILE):
        return None

    try:
        with open(TOKENS_FILE, 'r') as file:
            data = json.load(file)
            tokens = data.get('tokens', [])
            timestamp_str = data.get('timestamp')
        
        if not tokens or not timestamp_str:
            return None

        # Chuyển timestamp string thành đối tượng datetime
        loaded_time = datetime.fromisoformat(timestamp_str)
        
        # Kiểm tra nếu token còn hiệu lực
        time_elapsed = datetime.now() - loaded_time
        if time_elapsed < timedelta(hours=TOKEN_LIFETIME_HOURS):
            print(f"Loaded {len(tokens)} tokens from file. Valid for {timedelta(hours=TOKEN_LIFETIME_HOURS) - time_elapsed} more.")
            return tokens
        else:
            print("Tokens found in file but have expired. Need to refresh.")
            return None # Hết hạn
            
    except Exception as e:
        print(f"Error loading tokens from file: {e}")
        return None

def save_tokens(tokens):
    """Lưu token và timestamp hiện tại vào file."""
    try:
        data = {
            "tokens": tokens,
            "timestamp": datetime.now().isoformat() # Lưu thời gian hiện tại
        }
        with open(TOKENS_FILE, 'w') as file:
            json.dump(data, file, indent=4)
        print(f"Saved {len(tokens)} new tokens to {TOKENS_FILE}.")
    except Exception as e:
        print(f"Error saving tokens to file: {e}")

# --- 3. Lấy token từ API (Giữ nguyên) ---
async def fetch_token(session, uid, password):
    """Gọi API để lấy token từ UID và mật khẩu."""
    url = f"https://api-jwt-ag-team.vercel.app/get?uid={uid}&password={password}"
    try:
        async with session.get(url, timeout=25) as res:
            if res.status == 200:
                text = await res.text()
                try:
                    data = json.loads(text)
                    if isinstance(data, list) and len(data) > 0 and "token" in data[0]:
                        return data[0]["token"]
                    elif isinstance(data, dict) and "token" in data:
                        return data["token"]
                    else:
                        print(f"Unexpected token format for UID {uid}: {data}")
                except json.JSONDecodeError as e:
                    print(f"JSON decode error for UID {uid}: {e}")
                    print(f"Response text: {text}")
            else:
                print(f"API returned status {res.status} for UID {uid}")
    except Exception as e:
        print(f"Error fetching token for UID {uid}: {e}")
    return None

# --- 4. Lấy tất cả token (Tự động cập nhật nếu cần) ---
async def get_valid_tokens():
    """Tải token từ file, nếu hết hạn sẽ gọi API làm mới và lưu lại."""
    # 1. Thử tải token từ file
    tokens = load_tokens()
    if tokens is not None:
        return tokens

    # 2. Nếu không có token hợp lệ (hết hạn/chưa có file), tiến hành lấy token mới
    print("Tokens are expired or missing. Fetching new tokens from API...")
    accounts = load_accounts()
    if not accounts:
        print("No accounts loaded.")
        return []

    new_tokens = []
    async with aiohttp.ClientSession() as session:
        # Tạo danh sách task để gọi fetch_token cho từng tài khoản
        tasks = [fetch_token(session, uid, password) for uid, password in accounts.items()]
        # Chạy đồng thời tất cả các task
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Lọc các token thành công
        new_tokens = [token for token in results if isinstance(token, str) and token]

    # 3. Lưu token mới vào file
    if new_tokens:
        save_tokens(new_tokens)

    print(f"Fetched and saved {len(new_tokens)} new tokens.")
    return new_tokens

# --- 5. Logic gửi friend request (Giữ nguyên) ---
def send_friend_request(uid, token, results):
    """Gửi yêu cầu kết bạn đến một UID sử dụng một token."""
    encrypted_id = Encrypt_ID(uid)
    payload = f"08a7c4839f1e10{encrypted_id}1801"
    encrypted_payload = encrypt_api(payload)
    url = "https://clientbp.ggwhitehawk.com/RequestAddingFriend"
    headers = {
        "Expect": "100-continue",
        "Authorization": f"Bearer {token}",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB51",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": "16",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; SM-N975F Build/PI)",
        "Host": "clientbp.ggwhitehawk.com",
        "Connection": "close",
        "Accept-Encoding": "gzip, deflate, br"
    }
    try:
        response = requests.post(url, headers=headers, data=bytes.fromhex(encrypted_payload))
        if response.status_code == 200:
            results["success"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        print(f"Error sending request for UID {uid}: {e}")
        results["failed"] += 1

# --- 6. Endpoint chính ---
@app.route("/send_requests", methods=["GET"])
def send_requests():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "uid parameter is required"}), 400

    # Lấy token (từ file hoặc API)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Thay đổi từ get_tokens_live() sang get_valid_tokens()
        tokens = loop.run_until_complete(get_valid_tokens()) 
    finally:
        loop.close()

    if not tokens:
        return jsonify({"error": "No valid tokens found"}), 500

    # Gửi yêu cầu với từng token
    results = {"success": 0, "failed": 0}
    threads = []
    for token in tokens[:100]: # Giới hạn số lượng token max 100
        thread = threading.Thread(target=send_friend_request, args=(uid, token, results))
        threads.append(thread)
        thread.start()

    # Đợi tất cả các thread hoàn thành
    for thread in threads:
        thread.join()

    total_requests = results["success"] + results["failed"]
    status = 1 if results["success"] != 0 else 2

    return jsonify({
        "success_count": results["success"],
        "failed_count": results["failed"],
        "status": status
    })

# --- 7. Endpoint đơn giản kiểm tra (Giữ nguyên) ---
@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Friend Request API with Auto Token is running ✅"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
