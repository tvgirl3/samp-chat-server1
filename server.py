import socket
import threading
import time
import os

# Get host and port from environment variables
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 10000))

clients = {}
lock = threading.Lock()
BROADCAST_INTERVAL = 10.0
PING_TIMEOUT = 120.0

def safe_send(sock, text):
    try:
        sock.send(text.encode("utf-8", errors="ignore") + b"\n")
        return True
    except:
        return False

def build_players_payload():
    with lock:
        parts = []
        for info in clients.values():
            parts.append(f"{info['nick']};{info['server']};{info['status']}")
    return "PLAYERS|" + "|".join(parts)

def broadcast(message, exclude=None):
    dead = []
    with lock:
        sockets = list(clients.keys())
    
    for s in sockets:
        if s == exclude:
            continue
        if not safe_send(s, message):
            dead.append(s)
    
    if dead:
        with lock:
            for d in dead:
                if d in clients:
                    nick = clients[d].get('nick', 'Unknown')
                    print(f"[-] Removing dead connection: {nick}")
                    try:
                        d.close()
                    except:
                        pass
                    del clients[d]

def periodic_broadcast():
    while True:
        time.sleep(BROADCAST_INTERVAL)
        payload = build_players_payload()
        broadcast(payload)
        check_timeouts()

def check_timeouts():
    now = time.time()
    dead = []
    
    with lock:
        for sock, info in list(clients.items()):
            if now - info['last_seen'] > PING_TIMEOUT:
                dead.append((sock, info['nick']))
    
    for sock, nick in dead:
        print(f"[TIMEOUT] {nick}")
        with lock:
            if sock in clients:
                try:
                    sock.close()
                except:
                    pass
                del clients[sock]
        broadcast(f"[TIMEOUT] {nick} disconnected")

def handle_client(sock, addr):
    buffer = b""
    nickname = None
    server_name = "Unknown"
    registered = False

    try:
        sock.settimeout(2.0)
        
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                with lock:
                    if sock in clients:
                        clients[sock]["last_seen"] = time.time()
                continue
            except:
                break

            if not data:
                break

            buffer += data
            
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                msg = line.decode("utf-8", errors="ignore").strip()

                if not msg:
                    continue

                if not registered:
                    parts = msg.split("|")
                    if len(parts) >= 3:
                        nickname = parts[0]
                        server_name = parts[2]
                        
                        with lock:
                            clients[sock] = {
                                "nick": nickname,
                                "server": server_name,
                                "status": "ONLINE",
                                "last_seen": time.time()
                            }
                        
                        registered = True
                        print(f"[+] {nickname} connected ({server_name})")
                        
                        safe_send(sock, f"Welcome {nickname}!")
                        safe_send(sock, build_players_payload())
                        broadcast(f"[{server_name}] {nickname} joined", exclude=sock)
                    continue

                if msg.startswith("STATUS|"):
                    parts = msg.split("|")
                    if len(parts) >= 3:
                        new_status = parts[2].upper()
                        with lock:
                            if sock in clients:
                                old_status = clients[sock]["status"]
                                clients[sock]["status"] = new_status
                                clients[sock]["last_seen"] = time.time()
                        
                        if old_status != new_status:
                            print(f"[STATUS] {nickname}: {new_status}")
                            broadcast(build_players_payload())
                    continue

                if msg == "LIST":
                    safe_send(sock, build_players_payload())
                    with lock:
                        if sock in clients:
                            clients[sock]["last_seen"] = time.time()
                    continue

                if msg.startswith("DISCONNECT|"):
                    print(f"[DISCONNECT] {nickname}")
                    break

                print(f"[CHAT] {msg}")
                broadcast(msg, exclude=sock)
                
                with lock:
                    if sock in clients:
                        clients[sock]["last_seen"] = time.time()

    except Exception as e:
        print(f"[ERROR] {addr}: {e}")
    
    finally:
        if registered and nickname:
            print(f"[-] {nickname} disconnected")
            broadcast(f"[{server_name}] {nickname} left")
        
        with lock:
            if sock in clients:
                try:
                    sock.close()
                except:
                    pass
                del clients[sock]

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((HOST, PORT))
        server.listen(100)
        print("=" * 50)
        print("SAMP Chat Server Started!")
        print(f"Listening on {HOST}:{PORT}")
        print("=" * 50)
    except Exception as e:
        print(f"[FATAL] {e}")
        return

    threading.Thread(target=periodic_broadcast, daemon=True).start()

    try:
        while True:
            try:
                client, addr = server.accept()
                print(f"[NEW] Connection from {addr}")
                threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()
            except Exception as e:
                print(f"[ERROR] {e}")
                time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server stopping...")
    
    finally:
        broadcast("Server shutting down...")
        server.close()
        print("[SHUTDOWN] Done")

if __name__ == "__main__":
    main()
