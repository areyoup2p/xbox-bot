import requests
import uuid
import threading
import time
import random
import argparse
import os
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

stop_event = threading.Event()
sessions = deque()
sessions_lock = threading.Lock()
stats = {"created": 0, "deleted": 0, "errors": 0}
stats_lock = threading.Lock()

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

class TokenManager:
    def __init__(self, tokens):
        self.tokens = [t.strip() for t in tokens if t.strip()]
        self.lock = threading.Lock()
        self.index = 0
        self.bad = set()

    def get(self):
        with self.lock:
            if not self.tokens:
                return None
            start = self.index
            while True:
                token = self.tokens[self.index]
                self.index = (self.index + 1) % len(self.tokens)
                if token not in self.bad:
                    return token
                if self.index == start:
                    return None

    def mark_bad(self, token):
        with self.lock:
            self.bad.add(token)

def load_tokens(path):
    if not os.path.exists(path):
        print(f"{RED}No tokens file: {path}{RESET}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return f.readlines()

def load_texts(path):
    if not path or not os.path.exists(path):
        return ["LF people to play with rn"]
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def load_saved_sessions(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]

def save_sessions(path):
    with sessions_lock:
        with open(path, "w", encoding="utf-8") as f:
            for s in sessions:
                f.write(s + "\n")

def make_payload(text, xuid, join_rest, read_rest, target, vis):
    return {
        "properties": {
            "system": {
                "joinRestriction": join_rest,
                "readRestriction": read_rest,
                "description": {"locale": "en-US", "text": text},
                "searchHandleVisibility": vis
            }
        },
        "members": {
            "me": {
                "constants": {
                    "system": {"initialize": True, "xuid": xuid}
                }
            }
        },
        "roleTypes": {
            "lfg": {
                "roles": {
                    "confirmed": {"target": target}
                }
            }
        }
    }

def make_search_payload(scid, sid, tags):
    return {
        "type": "search",
        "sessionRef": {
            "scid": scid,
            "templateName": "global(lfg)",
            "name": sid
        },
        "searchAttributes": {
            "tags": tags,
            "achievementIds": [],
            "locale": "en"
        }
    }

def delete_one(sid, headers, scid):
    try:
        url = f"https://sessiondirectory.xboxlive.com/serviceconfigs/{scid}/sessiontemplates/global(lfg)/sessions/{sid}/members/me"
        r = requests.delete(url, headers=headers, timeout=8)
        if r.status_code in (200, 204):
            with stats_lock:
                stats["deleted"] += 1
            print(f"{YELLOW}[-] {sid}{RESET}")
            return True
    except:
        pass
    return False

def worker(tm, texts, args):
    headers_base = {
        "x-xbl-contract-version": "107",
        "User-Agent": "okhttp/3.12.1",
        "X-UserAgent": "Android/191121000 SM-A715F.AndroidPhone"
    }
    scid = args.scid
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    while not stop_event.is_set():
        token = tm.get()
        if not token:
            time.sleep(3)
            continue

        headers = headers_base.copy()
        headers["authorization"] = token

        sid = str(uuid.uuid4())
        text = random.choice(texts)

        payload = make_payload(text, args.xuid, args.join, args.read, args.target, args.vis)

        url = f"https://sessiondirectory.xboxlive.com/serviceconfigs/{scid}/sessiontemplates/global(lfg)/sessions/{sid}"
        try:
            r = requests.put(url, json=payload, headers=headers, timeout=12)

            if r.status_code in (201, 204):
                with stats_lock:
                    stats["created"] += 1
                print(f"{GREEN}[+] {sid}   {text[:50]}{'...' if len(text)>50 else ''}{RESET}")

                old = None
                with sessions_lock:
                    sessions.append(sid)
                    if args.max_active > 0 and len(sessions) > args.max_active:
                        old = sessions.popleft()

                if old:
                    time.sleep(random.uniform(args.delay_min, args.delay_max))
                    delete_one(old, headers, scid)

                requests.post(
                    "https://sessiondirectory.xboxlive.com/handles?include=relatedInfo",
                    json=make_search_payload(scid, sid, tags),
                    headers=headers,
                    timeout=8
                )

            elif r.status_code in (401, 403):
                print(f"{RED}bad token{RESET}")
                tm.mark_bad(token)
                with stats_lock:
                    stats["errors"] += 1
            else:
                with stats_lock:
                    stats["errors"] += 1

            time.sleep(random.uniform(0.1, 0.6))

        except:
            with stats_lock:
                stats["errors"] += 1
            time.sleep(1.2)

def status_loop():
    while not stop_event.is_set():
        time.sleep(6)
        if stop_event.is_set():
            break
        with stats_lock:
            active = len(sessions)
        print(f"\n{YELLOW} {datetime.now().strftime('%H:%M:%S')}  created:{stats['created']:,}  active:{active}  del:{stats['deleted']:,}  err:{stats['errors']:,} {RESET}\n")

def cleanup(args):
    sids = load_saved_sessions(args.sessions)
    if not sids:
        print(f"{RED}no saved sessions found{RESET}")
        return

    print(f"{YELLOW}cleaning {len(sids)} sessions...{RESET}")
    tokens = load_tokens(args.tokens)
    tm = TokenManager(tokens)

    def clean_one(sid):
        tok = tm.get()
        if not tok:
            return
        h = {
            "x-xbl-contract-version": "107",
            "authorization": tok,
            "User-Agent": "okhttp/3.12.1",
            "X-UserAgent": "Android/191121000 SM-A715F.AndroidPhone"
        }
        delete_one(sid, h, args.scid)

    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        ex.map(clean_one, sids)

    print(f"{GREEN}cleanup done{RESET}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["create","clean"], default="create")
    p.add_argument("--tokens", default="tokens.txt")
    p.add_argument("--sessions", default="mysessions.txt")
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--delay-min", type=float, default=0.7, dest="delay_min")
    p.add_argument("--delay-max", type=float, default=2.2, dest="delay_max")
    p.add_argument("--text")
    p.add_argument("--texts", dest="texts_file")
    p.add_argument("--max-active", type=int, default=6, help="0 = no limit")
    p.add_argument("--xuid", default="2535436196910107")
    p.add_argument("--scid", default="93ac0100-efec-488c-af85-e5850ff4b5bd")
    p.add_argument("--join", default="followed", dest="join")
    p.add_argument("--read", default="followed", dest="read")
    p.add_argument("--vis", default="xboxlive", dest="vis")
    p.add_argument("--tags", default="micrequired,textchatrequired")
    p.add_argument("--target", type=int, default=12)

    args = p.parse_args()

    if args.mode == "clean":
        cleanup(args)
        return

    tokens = load_tokens(args.tokens)
    tm = TokenManager(tokens)
    texts = [args.text] if args.text else load_texts(args.texts_file)

    print(f"{GREEN}starting  tokens:{len(tokens)}  texts:{len(texts)}  threads:{args.threads}  keep:{args.max_active or '∞'}{RESET}")

    threading.Thread(target=status_loop, daemon=True).start()

    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        for _ in range(args.threads):
            ex.submit(worker, tm, texts, args)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()

    print(f"\n{YELLOW}saving {len(sessions)} sessions...{RESET}")
    save_sessions(args.sessions)
    print(f"{GREEN}done{RESET}")

if __name__ == "__main__":
    main()
