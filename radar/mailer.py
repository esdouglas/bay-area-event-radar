"""Real e-mail for the Monday digest and book-ahead alerts, sent through the owner's own Gmail over SMTP.

Free: a Gmail app password (Google Account > Security > 2-Step Verification > App passwords) stored as
the repo secret GMAIL_APP_PASSWORD, plus RADAR_EMAIL (the Gmail address, used as sender and recipient;
kept as a secret so the address is not in this public repo). Without both secrets nothing is sent and
notify falls back to GitHub issues, exactly as before.
"""
import html
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

SENDER_NAME = "Bay Area Event Radar"
ACCENT = "#8a3b12"
INK = "#1f1d1a"
MUTED = "#6b665e"
RULE = "#e6e1d8"


def configured() -> bool:
    return bool(os.environ.get("RADAR_EMAIL") and os.environ.get("GMAIL_APP_PASSWORD"))


def send(subject: str, html_body: str, text_body: str) -> bool:
    """Send one message to RADAR_EMAIL. Returns False (never raises) so callers can fall back."""
    addr = os.environ.get("RADAR_EMAIL", "")
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not (addr and pw):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, addr))
    msg["To"] = addr
    msg["Message-ID"] = make_msgid(domain="event-radar.local")
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(addr, pw)
            s.send_message(msg)
        print(f"[mail] sent: {subject}")
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[mail] send failed ({type(exc).__name__}): {exc}")
        return False


# ----------------------------------------------------------------------------- rendering
# A digest is a list of sections: {"title": str, "cards": [card], "lines": [line]}
#   card = {"title", "when", "where", "tags": [str], "why", "links": [(label, url)]}
#   line = {"when", "title", "where", "tag"}
def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _button(label, url) -> str:
    return (f'<a href="{_e(url)}" style="display:inline-block;margin:0 8px 0 0;padding:5px 12px;border:1px solid {ACCENT};'
            f'border-radius:4px;color:{ACCENT};text-decoration:none;font-size:13px;">{_e(label)}</a>')


def render_html(heading: str, intro: str, sections: list, footer_links: list, footer_note: str = "") -> str:
    out = [f'<!doctype html><html><body style="margin:0;padding:0;background:#f7f4ee;">'
           f'<div style="max-width:600px;margin:0 auto;padding:24px 20px;font-family:Georgia,\'Times New Roman\',serif;color:{INK};">'
           f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{ACCENT};">Bay Area Event Radar</div>'
           f'<h1 style="font-size:26px;line-height:1.25;margin:6px 0 8px;font-weight:normal;">{_e(heading)}</h1>'
           f'<p style="font-size:16px;line-height:1.5;color:{MUTED};margin:0 0 8px;">{_e(intro)}</p>']
    for sec in sections:
        if not (sec.get("cards") or sec.get("lines") or sec.get("empty")):
            continue
        out.append(f'<h2 style="font-family:Helvetica,Arial,sans-serif;font-size:13px;letter-spacing:.08em;text-transform:uppercase;'
                   f'color:{MUTED};border-top:1px solid {RULE};padding-top:18px;margin:26px 0 4px;">{_e(sec["title"])}</h2>')
        if sec.get("empty") and not sec.get("cards"):
            out.append(f'<p style="font-size:15px;color:{MUTED};">{_e(sec["empty"])}</p>')
        for c in sec.get("cards", []):
            tags = "".join(f'<span style="display:inline-block;margin:0 6px 4px 0;padding:1px 8px;background:#efe9df;border-radius:10px;'
                           f'font-family:Helvetica,Arial,sans-serif;font-size:12px;color:{MUTED};">{_e(t)}</span>' for t in c.get("tags", []))
            links = "".join(_button(l, u) for l, u in c.get("links", []) if u)
            out.append(f'<div style="padding:14px 0 16px;border-bottom:1px solid {RULE};">'
                       f'<div style="font-size:19px;line-height:1.3;font-weight:bold;">{_e(c["title"])}</div>'
                       f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:{ACCENT};margin:4px 0 6px;">{_e(c["when"])} &middot; {_e(c["where"])}</div>'
                       + (f'<div style="margin:2px 0 6px;">{tags}</div>' if tags else "")
                       + f'<div style="font-size:15px;line-height:1.55;">{_e(c["why"])}</div>'
                       + (f'<div style="margin-top:10px;">{links}</div>' if links else "") + '</div>')
        if sec.get("lines"):
            out.append('<table role="presentation" style="width:100%;border-collapse:collapse;font-family:Helvetica,Arial,sans-serif;font-size:14px;">')
            for ln in sec["lines"]:
                title = f'<a href="{_e(ln["url"])}" style="color:{INK};">{_e(ln["title"])}</a>' if ln.get("url") else _e(ln["title"])
                out.append(f'<tr><td style="padding:6px 10px 6px 0;color:{MUTED};white-space:nowrap;vertical-align:top;">{_e(ln["when"])}</td>'
                           f'<td style="padding:6px 0;vertical-align:top;">{title}<br><span style="color:{MUTED};font-size:13px;">{_e(ln["where"])}'
                           + (f' &middot; {_e(ln["tag"])}' if ln.get("tag") else "") + '</span></td></tr>')
            out.append('</table>')
    foot = " &middot; ".join(f'<a href="{_e(u)}" style="color:{MUTED};">{_e(l)}</a>' for l, u in footer_links)
    out.append(f'<p style="font-family:Helvetica,Arial,sans-serif;font-size:12px;color:{MUTED};margin-top:28px;line-height:1.6;">{foot}'
               + (f'<br>{_e(footer_note)}' if footer_note else "") + '</p></div></body></html>')
    return "".join(out)


def render_text(heading: str, intro: str, sections: list, footer_links: list, footer_note: str = "") -> str:
    out = [heading, "", intro, ""]
    for sec in sections:
        if not (sec.get("cards") or sec.get("lines") or sec.get("empty")):
            continue
        out += [sec["title"].upper(), ""]
        if sec.get("empty") and not sec.get("cards"):
            out += [sec["empty"], ""]
        for c in sec.get("cards", []):
            out += [c["title"], f"{c['when']} · {c['where']}" + (f" ({', '.join(c['tags'])})" if c.get("tags") else ""), c["why"]]
            out += [f"{l}: {u}" for l, u in c.get("links", []) if u] + [""]
        for ln in sec.get("lines", []):
            out.append(f"- {ln['when']} · {ln['title']} · {ln['where']}" + (f" · {ln['tag']}" if ln.get("tag") else ""))
        if sec.get("lines"):
            out.append("")
    out += [f"{l}: {u}" for l, u in footer_links]
    if footer_note:
        out.append(footer_note)
    return "\n".join(out)


def render_markdown(intro: str, sections: list, footer_links: list, footer_note: str = "") -> str:
    """Same content as an issue body (fallback channel and permanent record)."""
    out = [intro, ""]
    for sec in sections:
        if not (sec.get("cards") or sec.get("lines") or sec.get("empty")):
            continue
        out.append(f"## {sec['title']}")
        if sec.get("empty") and not sec.get("cards"):
            out.append(sec["empty"] + "\n")
        for c in sec.get("cards", []):
            links = " ".join(f"[{l.lower()}]({u})" for l, u in c.get("links", []) if u)
            out.append(f"**{c['title']}**  \n{c['when']} · {c['where']}" + (f" · {' · '.join(c['tags'])}" if c.get("tags") else "")
                       + f"  \n{c['why']}  \n{links}\n")
        out += [f"- {ln['when']} · {ln['title']} · {ln['where']}" + (f" · {ln['tag']}" if ln.get("tag") else "") for ln in sec.get("lines", [])]
        if sec.get("lines"):
            out.append("")
    if footer_note:
        out.append(f"<sub>{footer_note}</sub>  ")
    out.append("<sub>" + " · ".join(f"[{l}]({u})" for l, u in footer_links) + "</sub>")
    return "\n".join(out)
