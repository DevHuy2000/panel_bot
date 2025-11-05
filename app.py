# app1_auto_token.py
# app1_auto_token.py
from flask import Flask, request, jsonify
import requests
import json
import threading
import asyncio
import aiohttp
from byte import Encrypt_ID, encrypt_api # Giả sử bạn có các module này

app = Flask(__name__)

# --- 1. Tải tài khoản từ accounts.txt ---
# Định dạng accounts.txt là một list các object {uid, password}
# Chúng ta sẽ chuyển đổi nó thành một dict {uid: password}
ACCOUNTS_FILE = 'accounts.json'

def load_accounts():
    """Đọc UID và mật khẩu từ file accounts.txt (dạng list object) và chuyển thành dict."""
    try:
        with open(ACCOUNTS_FILE, 'r') as file:
            accounts_list = json.load(file) # Đọc file như một list

        # Chuyển list object thành dict {uid: password}
        accounts_dict = {}
        for account in accounts_list:
            uid = account.get('uid')
            password = account.get('password')
            if uid and password: # Kiểm tra xem uid và password có tồn tại không
                accounts_dict[uid] = password
            else:
                print(f"Warning: Invalid account entry skipped: {account}")

        print(f"Loaded {len(accounts_dict)} accounts.")
        return accounts_dict # Trả về dict

    except FileNotFoundError:
        print(f"File {ACCOUNTS_FILE} not found.")
        return {}
    except Exception as e:
        print(f"Error loading accounts: {e}")
        return {}

# --- 2. Lấy token từ API ---
async def fetch_token(session, uid, password):
    """Gọi API để lấy token từ UID và mật khẩu."""
    url = f"https://VipCoringaJWT.vercel.app/token?uid={uid}&password={password}"
    try:
        async with session.get(url, timeout=25) as res:
            if res.status == 200:
                text = await res.text()
                try:
                    data = json.loads(text)
                    # Kiểm tra định dạng dữ liệu trả về từ API
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
    return None # Trả về None nếu thất bại

# --- 3. Lấy tất cả token ---
async def get_tokens_live():
    """Lấy tất cả token từ danh sách tài khoản."""
    accounts = load_accounts()
    if not accounts:
        print("No accounts loaded.")
        return []

    tokens = []
    async with aiohttp.ClientSession() as session:
        # Tạo danh sách task để gọi fetch_token cho từng tài khoản
        tasks = [fetch_token(session, uid, password) for uid, password in accounts.items()]
        # Chạy đồng thời tất cả các task
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Lọc các token thành công
        tokens = [token for token in results if isinstance(token, str) and token]

    print(f"Fetched {len(tokens)} tokens.")
    return tokens

# --- 4. Logic gửi friend request ---
def send_friend_request(uid, token, results):
    """Hàm gửi friend request cho một token cụ thể."""
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

# --- 5. Endpoint chính ---
@app.route("/send_requests", methods=["GET"])
def send_requests():
    """Endpoint để gửi friend request cho một UID cụ thể."""
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "uid parameter is required"}), 400

    # Lấy token từ API
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        tokens = loop.run_until_complete(get_tokens_live())
    finally:
        loop.close()

    if not tokens:
        return jsonify({"error": "No valid tokens found"}), 500

    # Gửi yêu cầu với từng token
    results = {"success": 0, "failed": 0}
    threads = []
    for token in tokens[:100]: # Giới hạn số lượng token gửi (tùy chọn)
        thread = threading.Thread(target=send_friend_request, args=(uid, token, results))
        threads.append(thread)
        thread.start()

    # Đợi tất cả các thread hoàn thành
    for thread in threads:
        thread.join()

    total_requests = results["success"] + results["failed"]
    status = 1 if results["success"] != 0 else 2  # Tùy chỉnh logic status theo nhu cầu

    return jsonify({
        "success_count": results["success"],
        "failed_count": results["failed"],
        "status": status
    })

# --- 6. Endpoint đơn giản kiểm tra ---
@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Friend Request API with Auto Token is running ✅"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
