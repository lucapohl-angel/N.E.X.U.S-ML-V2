"""Localhost-only browser reviewer for one engine-drafted game."""
# ruff: noqa: E501

from __future__ import annotations

import io
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw
from pydantic import JsonValue

from nexus_v2.ocr.normalize import parse_ocr
from nexus_v2.review.dataset import (
    GameCapture,
    ReviewDecision,
    ReviewRecord,
    ReviewState,
    parse_edited_value,
    save_review_state,
    utc_now,
)
from nexus_v2.review.export import TruthExporter

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>N.E.X.U.S Review</title>
<style>
:root{color-scheme:dark;--bg:#090b10;--panel:#121722;--line:#2b3444;--red:#ff3348;--green:#4ade80;--muted:#94a3b8;--text:#f8fafc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;height:100vh;overflow:hidden}
header{height:58px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:18px;padding:0 18px;background:#0d1119}header b{letter-spacing:.12em}.progress{flex:1;height:8px;background:#222a37;border-radius:5px;overflow:hidden}.progress>i{display:block;height:100%;background:var(--red);width:0}.count{font-variant-numeric:tabular-nums;color:var(--muted)}
main{display:grid;grid-template-columns:minmax(0,1fr) 390px;height:calc(100vh - 58px)}.visual{min-width:0;padding:14px;display:grid;grid-template-rows:minmax(0,1fr) 180px;gap:12px}.stage{position:relative;display:flex;align-items:center;justify-content:center;min-height:0;background:#050609;border:1px solid var(--line);overflow:hidden}.frame{position:relative;line-height:0;max-width:100%;max-height:100%}.frame img{display:block;max-width:100%;max-height:calc(100vh - 278px);object-fit:contain}.highlight{position:absolute;border:3px solid var(--red);box-shadow:0 0 0 9999px rgba(0,0,0,.34),0 0 20px var(--red);pointer-events:none}.crop{border:1px solid var(--line);background:#050609;display:flex;align-items:center;justify-content:center;overflow:hidden}.crop img{max-width:100%;max-height:100%;image-rendering:auto}
aside{border-left:1px solid var(--line);background:var(--panel);padding:0;overflow:hidden;min-height:0}#review{height:100%;display:flex;flex-direction:column;min-height:0}.review-content{flex:1 1 auto;min-height:0;overflow:auto;padding:18px 18px 10px}.decision-dock{flex:0 0 auto;padding:12px 18px 18px;border-top:1px solid var(--line);background:#101620;box-shadow:0 -10px 24px rgba(0,0,0,.28)}.path{font-size:12px;color:var(--muted);word-break:break-all}.field{font-size:25px;margin:10px 0 4px}.tags{display:flex;gap:6px;flex-wrap:wrap}.tag{border:1px solid var(--line);padding:4px 7px;font-size:12px;color:#cbd5e1}.tag.bad{border-color:#7f1d1d;color:#fecaca}.prediction{margin:18px 0;background:#090c12;border:1px solid var(--line);padding:14px}.prediction label,.section-title{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.13em;margin-bottom:8px}.prediction pre{white-space:pre-wrap;word-break:break-word;font-size:18px;margin:0}.candidates{font-size:12px;color:#cbd5e1;max-height:100px;overflow:auto}.candidates div{padding:4px 0;border-bottom:1px solid #202735}
input{width:100%;background:#07090d;color:white;border:1px solid #475569;padding:11px;font-size:15px;margin-top:8px}.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0}.actions button{height:48px;padding:8px;line-height:1.2;overflow:hidden}button{border:1px solid var(--line);background:#1a2230;color:white;padding:11px;cursor:pointer;font-weight:650}button:hover{border-color:#64748b}.accept{background:#11602d;border-color:#22c55e}.edit{background:#7f1d1d;border-color:var(--red)}.unknown{background:#3b2b0e;border-color:#a16207}.wide{grid-column:1/-1}.actions .wide{height:44px}.help{margin-top:17px;font-size:12px;line-height:1.6;color:var(--muted)}.done{display:none;padding:30px;text-align:center}.error{color:#fca5a5;min-height:20px;font-size:13px;margin-top:8px}
@media(max-width:900px){main{grid-template-columns:1fr}.visual{display:none}aside{border-left:0}.field{font-size:21px}}
</style>
</head>
<body>
<header><b>N.E.X.U.S TRUTH REVIEW</b><div class="progress"><i id="bar"></i></div><span class="count" id="count">Loading…</span></header>
<main>
<section class="visual"><div class="stage"><div class="frame" id="frame"><img id="source"><div class="highlight" id="highlight"></div></div></div><div class="crop"><img id="crop"></div></section>
<aside>
<div id="review">
<div class="review-content">
<div class="path" id="path"></div><h1 class="field" id="field"></h1><div class="tags" id="tags"></div>
<div class="prediction"><label>Engine draft — not truth until approved</label><pre id="prediction"></pre></div><div class="prediction" id="repeatBox" style="display:none;border-color:#22c55e"><label>Previously confirmed in this game</label><pre id="repeatValue"></pre><div class="path" id="repeatSource"></div></div>
<label class="section-title">Correct value</label><input id="editValue" list="correctionOptions" autocomplete="off"><datalist id="correctionOptions"></datalist><div class="error" id="error"></div>
<div class="section-title" style="margin-top:18px">Candidates</div><div class="candidates" id="candidates"></div>
<div class="help"><b>Prediction correct:</b> press Y. <b>Prediction wrong:</b> type the correction and press Enter or Save correction—do not press Y afterward. A green previously-confirmed value is prefilled from an earlier tab; press Y to reuse it after checking the crop. Keyboard: <b>Y</b> confirm · <b>E</b> edit · <b>U</b> unreadable · <b>S</b> skip · <b>B</b> back. Progress saves after every decision.</div>
</div>
<div class="decision-dock"><div class="actions"><button class="accept" id="acceptButton" onclick="acceptCurrent()">Y — Prediction is correct</button><button class="edit" onclick="decide('edit')">E — Save correction</button><button class="unknown" onclick="decide('unknown')">U — Unreadable / unknown</button><button onclick="decide('skip')">S — Skip for now</button><button class="wide" onclick="decide('back')">B — Previous field</button></div></div>
</div><div class="done" id="done"><h2>Game review complete</h2><p>All fields are approved, edited, or explicitly unknown.</p></div>
</aside></main>
<script>
let state=null;
const $=id=>document.getElementById(id);
function esc(v){return v===null?'EMPTY / NULL':typeof v==='object'?JSON.stringify(v,null,2):String(v)}
async function load(){const r=await fetch('/api/state',{cache:'no-store'});state=await r.json();render()}
function render(){
 const total=state.total,reviewed=state.counts.accepted+state.counts.edited+state.counts.unknown;
 $('count').textContent=`${state.index+1}/${total} · ${reviewed} final · ${state.counts.skipped} skipped`;$('bar').style.width=`${total?reviewed/total*100:100}%`;
 if(state.done){$('review').style.display='none';$('done').style.display='block';return}
 $('review').style.display='flex';$('done').style.display='none';const c=state.current;
 $('path').textContent=`${state.family_id} / ${state.game_id} / ${c.screenshot}`;$('field').textContent=c.field_id;
 const tags=[c.kind,c.side&&`side: ${c.side}`,c.row!==null&&`row: ${c.row+1}`,c.slot!==null&&`slot: ${c.slot+1}`,c.review_reason&&`reason: ${c.review_reason}`,`status: ${c.extraction_status}`,c.confidence!==null&&`score: ${c.confidence.toFixed(4)}`].filter(Boolean);
 $('tags').innerHTML=tags.map((t,i)=>`<span class="tag ${c.extraction_status==='ok'?'':'bad'}">${t}</span>`).join('');
 const repeated=state.repeated_truth,suggested=!repeated&&c.suggested_value!==null?c.suggested_value:null;$('prediction').textContent=c.display_prediction||esc(c.prediction);$('repeatBox').style.display=repeated?'block':'none';if(repeated){$('repeatValue').textContent=esc(repeated.value);$('repeatSource').textContent=`Confirmed on ${repeated.source_screenshot}`;}$('acceptButton').textContent=repeated?'Y — Use confirmed value':suggested!==null?'Y — Use OCR suggestion':'Y — Prediction is correct';const initialValue=repeated?repeated.value:suggested!==null?suggested:c.prediction;$('editValue').value=typeof initialValue==='object'&&initialValue!==null?JSON.stringify(initialValue):initialValue??'';$('error').textContent='';
 $('correctionOptions').innerHTML=(state.correction_options||[]).map(x=>`<option value="${x.replaceAll('&','&amp;').replaceAll('"','&quot;')}"></option>`).join('');
 $('candidates').innerHTML=(c.candidates.length?c.candidates:['No alternative candidates recorded']).map(x=>`<div>${x.replaceAll('&','&amp;').replaceAll('<','&lt;')}</div>`).join('');
 const nonce=Date.now();$('source').src=`/source/${encodeURIComponent(c.screenshot)}?v=${nonce}`;$('crop').src=`/crop.png?v=${nonce}`;
 $('source').onload=()=>positionBox(c);
}
function positionBox(c){const img=$('source'),box=$('highlight');if(!c.source_box){box.style.display='none';return}box.style.display='block';const [x1,y1,x2,y2]=c.source_box;box.style.left=`${x1/state.image_width*100}%`;box.style.top=`${y1/state.image_height*100}%`;box.style.width=`${(x2-x1)/state.image_width*100}%`;box.style.height=`${(y2-y1)/state.image_height*100}%`}
async function decide(action){$('error').textContent='';const payload={action};if(action==='edit')payload.value=$('editValue').value;const r=await fetch('/api/decision',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok){$('error').textContent=data.error||'Decision failed';return}state=data;render()}
function acceptCurrent(){(state.repeated_truth||state.current.suggested_value!==null)?decide('edit'):decide('accept')}
document.addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;const input=document.activeElement===$('editValue');if(input){if(e.key==='Enter'){e.preventDefault();decide('edit')}return}const k=e.key.toLowerCase();if(k==='y')acceptCurrent();else if(k==='e')$('editValue').focus();else if(k==='u')decide('unknown');else if(k==='s')decide('skip');else if(k==='b')decide('back')});
load().catch(e=>$('error').textContent=e.message);
</script></body></html>"""


class ReviewSession:
    def __init__(
        self,
        capture: GameCapture,
        state: ReviewState,
        *,
        correction_options: dict[str, tuple[tuple[str, str], ...]] | None = None,
        truth_exporter: TruthExporter | None = None,
    ) -> None:
        self.capture = capture
        self.state = state
        self.correction_options = correction_options or {}
        self.truth_exporter = truth_exporter
        self.lock = RLock()
        self._normalize_index()

    def _normalize_index(self) -> None:
        if not self.state.records:
            self.state.current_index = 0
        else:
            self.state.current_index = min(self.state.current_index, len(self.state.records))

    def _next_unfinished(self, start: int) -> int | None:
        records = self.state.records
        unfinished = {ReviewDecision.PENDING, ReviewDecision.SKIPPED}
        for index in range(start, len(records)):
            if records[index].decision in unfinished:
                return index
        for index in range(0, start):
            if records[index].decision in unfinished:
                return index
        return None

    def public_state(self) -> dict[str, Any]:
        with self.lock:
            counts = self.state.counts()
            done = self.state.current_index >= len(self.state.records)
            current = None if done else self.state.records[self.state.current_index]
            repeated_truth = None if current is None else self._repeated_truth(current)
            width = height = 1
            if current is not None:
                with Image.open(self.capture.image_path(current.screenshot)) as image:
                    width, height = image.size
            return {
                "family_id": self.state.family_id,
                "game_id": self.state.game_id,
                "index": self.state.current_index,
                "total": len(self.state.records),
                "counts": counts,
                "done": done,
                "image_width": width,
                "image_height": height,
                "current": None if current is None else json.loads(current.model_dump_json()),
                "correction_options": (
                    []
                    if current is None
                    else [
                        f"{entity_id} — {name}"
                        for entity_id, name in self.correction_options.get(current.kind, ())
                    ]
                ),
                "repeated_truth": repeated_truth,
            }

    def _repeat_key(self, record: ReviewRecord) -> tuple[object, ...] | None:
        if self.capture.visual_batch_capture:
            return None
        if record.kind not in {"hero", "metadata", "ocr"}:
            return None
        return (record.kind, record.field_id, record.side, record.row, record.slot)

    def _repeated_truth(self, current: ReviewRecord) -> dict[str, JsonValue] | None:
        key = self._repeat_key(current)
        if key is None:
            return None
        matches = [
            record
            for record in self.state.records
            if record.record_id != current.record_id
            and self._repeat_key(record) == key
            and record.decision in {ReviewDecision.ACCEPTED, ReviewDecision.EDITED}
        ]
        if not matches:
            return None
        encoded = {
            json.dumps(record.truth_value, ensure_ascii=False, sort_keys=True) for record in matches
        }
        if len(encoded) != 1:
            return None
        source = max(matches, key=lambda record: record.reviewed_at or self.state.created_at)
        return {"value": source.truth_value, "source_screenshot": source.screenshot}

    def _parse_edit(self, record: ReviewRecord, edited_value: str) -> JsonValue:
        options = self.correction_options.get(record.kind)
        if not options:
            if record.parser is not None:
                parsed = parse_ocr(edited_value, parser=record.parser)
                if not parsed.valid:
                    raise ValueError("correction does not satisfy the field's semantic format")
                return parsed.value
            return parse_edited_value(edited_value, record.prediction)
        stripped = edited_value.strip()
        if record.kind == "item" and stripped.casefold() in {
            "empty",
            "empty slot",
            "none",
            "null",
            "__empty__",
        }:
            return None
        aliases: dict[str, str] = {}
        for entity_id, name in options:
            aliases[entity_id.casefold()] = entity_id
            aliases[name.casefold()] = entity_id
            aliases[f"{entity_id} — {name}".casefold()] = entity_id
        normalized = aliases.get(stripped.casefold())
        if normalized is None:
            raise ValueError(f"choose a valid {record.kind} ID or name from the correction list")
        return normalized

    def decide(self, action: str, edited_value: str | None = None) -> dict[str, Any]:
        with self.lock:
            if not self.state.records:
                raise ValueError("review queue is empty")
            if action == "back":
                self.state.current_index = max(
                    0, min(self.state.current_index, len(self.state.records)) - 1
                )
                save_review_state(self.capture, self.state)
                return self.public_state()
            record = self.state.records[self.state.current_index]
            now = utc_now()
            if action == "accept":
                updated = record.model_copy(
                    update={
                        "decision": ReviewDecision.ACCEPTED,
                        "truth_value": record.prediction,
                        "reviewed_at": now,
                    }
                )
            elif action == "edit":
                if edited_value is None:
                    raise ValueError("edited value is required")
                truth = self._parse_edit(record, edited_value)
                updated = record.model_copy(
                    update={
                        "decision": ReviewDecision.EDITED,
                        "truth_value": truth,
                        "reviewed_at": now,
                    }
                )
            elif action == "unknown":
                updated = record.model_copy(
                    update={
                        "decision": ReviewDecision.UNKNOWN,
                        "truth_value": None,
                        "reviewed_at": now,
                    }
                )
            elif action == "skip":
                updated = record.model_copy(
                    update={"decision": ReviewDecision.SKIPPED, "reviewed_at": now}
                )
            else:
                raise ValueError(f"unsupported decision: {action}")
            self.state.records[self.state.current_index] = updated
            next_index = self._next_unfinished(self.state.current_index + 1)
            self.state.current_index = len(self.state.records) if next_index is None else next_index
            save_review_state(self.capture, self.state)
            if self.state.complete and self.truth_exporter is not None:
                self.truth_exporter(self.capture, self.state)
            return self.public_state()

    def crop_png(self) -> bytes:
        with self.lock:
            if not self.state.records:
                raise ValueError("review queue is empty")
            record = self.state.records[min(self.state.current_index, len(self.state.records) - 1)]
            with Image.open(self.capture.image_path(record.screenshot)) as source:
                image = source.convert("RGB")
                if record.source_box is None:
                    crop = image.copy()
                else:
                    x1, y1, x2, y2 = record.source_box
                    padding = max(8, int(round(min(x2 - x1, y2 - y1) * 0.18)))
                    crop = image.crop(
                        (
                            max(0, x1 - padding),
                            max(0, y1 - padding),
                            min(image.width, x2 + padding),
                            min(image.height, y2 + padding),
                        )
                    )
                scale = min(6.0, 1300 / max(1, crop.width), 500 / max(1, crop.height))
                if scale > 1.0:
                    crop = crop.resize(
                        (int(round(crop.width * scale)), int(round(crop.height * scale))),
                        Image.Resampling.NEAREST,
                    )
                draw = ImageDraw.Draw(crop)
                draw.rectangle((0, 0, crop.width - 1, crop.height - 1), outline="#ff3348", width=3)
                output = io.BytesIO()
                crop.save(output, format="PNG", optimize=True)
                return output.getvalue()


def make_handler(session: ReviewSession) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "NexusReview/1"

        def log_message(self, format: str, *args: object) -> None:
            if self.path.startswith("/api/decision"):
                super().log_message(format, *args)

        def _headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:",
            )
            self.end_headers()

        def _send(self, payload: bytes, content_type: str, status: int = 200) -> None:
            self._headers(status, content_type, len(payload))
            self.wfile.write(payload)

        def _json(self, value: object, status: int = 200) -> None:
            self._send(
                json.dumps(value, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
                status,
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send(HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._json(session.public_state())
                return
            if parsed.path == "/crop.png":
                self._send(session.crop_png(), "image/png")
                return
            if parsed.path.startswith("/source/"):
                filename = parsed.path.removeprefix("/source/")
                try:
                    path = session.capture.image_path(filename)
                except ValueError:
                    self._json({"error": "unsupported source"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = "image/png" if path.suffix.casefold() == ".png" else "image/jpeg"
                self._send(path.read_bytes(), content_type)
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/decision":
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 65536:
                    raise ValueError("request body too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("request must be an object")
                action = body.get("action")
                value = body.get("value")
                if not isinstance(action, str):
                    raise ValueError("action is required")
                if value is not None and not isinstance(value, str):
                    raise ValueError("edited value must be text")
                self._json(session.decide(action, value))
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return Handler


def create_server(
    session: ReviewSession, *, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("review server may only bind to localhost")
    return ThreadingHTTPServer((host, port), make_handler(session))


__all__ = ["ReviewSession", "create_server", "make_handler"]
