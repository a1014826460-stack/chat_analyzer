
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import random
import time

from playwright.async_api import async_playwright

SDK_APP_ID = 20011216
ACCID = "A7MYtCxL8"
USER_SIG = "eJyrVgrxCdYrSy1SslIy0jNQ0gHzM1NS80oy0zLBwo7mvpElzhU*FlDJ4pTsxIKCzBSQDgMDQ0MjQzOoTGpFQWZRqpKVoZGlmYGBAUSwJDMXJGRuYWxsbmJhbgI1JDMdqD84KcvXMKssMi2zzNu9NCwos6AgzTfQOVzb2KmywrvQMCg5MqIi1SvFJMzTVqkWAJiPMnI_"


def frame(head: dict, body: dict) -> str:
    inner = json.dumps({"head": head, "body": body}, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"type": 3, "buffer": base64.b64encode(inner.encode()).decode()}, ensure_ascii=False)


def login_head(seq: int, accid: str, usersig: str, sdk_app_id: int) -> dict:
    return {
        "ver": "v4",
        "platform": 7,
        "websdkappid": 537048168,
        "websdkversion": "1.7.3",
        "status_instid": 0,
        "sdkappid": sdk_app_id,
        "contenttype": "json",
        "reqtime": int(time.time()),
        "identifier": accid,
        "usersig": usersig,
        "sdkability": 192371,
        "tjgID": "",
        "servcmd": "im_open_status.wslogin",
        "seq": seq,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accid", default=ACCID)
    ap.add_argument("--user-sig", default=USER_SIG)
    ap.add_argument("--sdk-app-id", type=int, default=SDK_APP_ID)
    ap.add_argument("--endpoint", default="wss://wsssgp.my-imcloud.com/binfo")
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument("--a2", default="")
    ap.add_argument("--tiny-id", default="")
    ap.add_argument("--status-instid", type=int, default=0)
    ap.add_argument("--instanceid", default="")
    args = ap.parse_args()

    instanceid = args.instanceid or ("%032x" % random.getrandbits(128))
    seq = random.randint(10_000_000, 99_999_999)
    url = (
        f"{args.endpoint}?sdkappid={args.sdk_app_id}&instanceid={instanceid}"
        f"&random={random.random()}&platform=7&host=windows&version=-1&sdkversion=3.2.1"
    )
    
    if args.a2:
        head = {
            "ver":"v4","platform":7,"websdkappid":537048168,"websdkversion":"1.7.3",
            "a2":args.a2,"tinyid":args.tiny_id,"status_instid":args.status_instid,
            "sdkappid":args.sdk_app_id,"contenttype":"json","reqtime":int(time.time()),
            "sdkability":192371,"tjgID":"","servcmd":"im_open_status.wslogin","seq":seq,
        }
    else:
        head = login_head(seq, args.accid, args.user_sig, args.sdk_app_id)
    payload = frame(head, {"State":"Online","is_web_uniapp":0,"InstType":0})
    print("url", url)
    print("seq", seq)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(ignore_https_errors=True)
        await page.goto("https://www.571919.xyz/", wait_until="commit", timeout=30000)
        print("page_url", page.url)
        print("origin", await page.evaluate("location.origin"))
        result = await page.evaluate(
            """async ({url, payload, heartbeat, timeoutMs}) => {
                return await new Promise((resolve) => {
                    const out = {events: []};
                    const ws = new WebSocket(url);
                    const timer = setTimeout(() => { out.timeout = true; try { ws.close(); } catch(e) {} resolve(out); }, timeoutMs);
                    ws.onopen = () => { out.events.push('open'); ws.send(payload); ws.send(heartbeat); out.events.push('sent2'); };
                    ws.onerror = (e) => { out.events.push('error'); out.error = String(e && e.message || e); };
                    ws.onclose = (e) => { out.events.push('close:' + e.code + ':' + e.reason); if (!out.done && !out.timeout) { clearTimeout(timer); resolve(out); } };
                    ws.onmessage = (e) => { out.events.push('message'); out.raw = e.data; out.done = true; clearTimeout(timer); try { ws.close(); } catch(err) {} resolve(out); };
                });
            }""",
            {"url": url, "payload": payload, "heartbeat": frame({**head, "servcmd":"heartbeat.alive", "seq": seq+1, "reqtime": int(time.time())}, {}), "timeoutMs": int(args.timeout * 1000)},
        )
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
        if result.get("raw"):
            outer = json.loads(result["raw"])
            inner = json.loads(base64.b64decode(outer["buffer"]).decode())
            print("decoded", json.dumps(inner, ensure_ascii=False, indent=2)[:4000])
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
