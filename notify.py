"""通知：默认关闭，配置 webhook_url 后启用（Server酱 / 企业微信 / 通用JSON）"""

import httpx


def send(webhook_url, title, content, log):
    if not webhook_url:
        return
    try:
        if "sctapi" in webhook_url or "serverchan" in webhook_url:
            payload = {"title": title, "desp": content}
        elif "qyapi" in webhook_url:
            payload = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
        else:
            payload = {"title": title, "content": content}
        r = httpx.post(webhook_url, json=payload, timeout=10)
        log(f"[notify] sent, status={r.status_code}")
    except Exception as e:
        log(f"[notify] failed: {str(e)[:120]}")
