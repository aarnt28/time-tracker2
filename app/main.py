from __future__ import annotations
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
import csv, io, os, re, json
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Header, Request, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, Response, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Text, or_, desc
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# ---------- Config ----------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_FILE = DATA_DIR / "data.db"
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

CENTRAL = ZoneInfo("America/Chicago")
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# honour external database URLs when provided (e.g. docker compose)
DEFAULT_DB_URL = f"sqlite:///{DB_FILE}"
DB_URL = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL


def _sqlite_connect_args(url: str) -> Dict[str, Any]:
    if not url.startswith("sqlite"):
        return {}
    connect_args: Dict[str, Any] = {"check_same_thread": False}
    try:
        url_obj = make_url(url)
        db_path = url_obj.database
        if db_path and db_path != ":memory:":
            path = Path(db_path)
            if not path.is_absolute():
                path = (BASE_DIR / db_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return connect_args


engine = create_engine(DB_URL, connect_args=_sqlite_connect_args(DB_URL))
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ---------- Model ----------
class Entry(Base):
    __tablename__ = "entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client = Column(Text, nullable=False)
    client_key = Column(Text, nullable=False)
    start_iso = Column(Text, nullable=False)
    end_iso = Column(Text, nullable=True)   # NULL when session is running

    # time accounting
    minutes = Column(Integer, nullable=False, default=0)
    rounded_minutes = Column(Integer, nullable=False, default=0)
    rounded_hours = Column(Text, nullable=False, default="0.00")
    # present in some live DBs
    elapsed_minutes = Column(Integer, nullable=False, default=0)

    note = Column(Text, nullable=True)
    completed = Column(Integer, nullable=False, default=0)
    invoice_number = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False, default=lambda: datetime.now(tz=CENTRAL).isoformat())

Base.metadata.create_all(engine)

# ---------- Lite migration (adds missing cols on old DBs) ----------
def migrate_schema():
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(entries)").all()}
        if "minutes" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN minutes INTEGER NOT NULL DEFAULT 0")
        if "rounded_minutes" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN rounded_minutes INTEGER NOT NULL DEFAULT 0")
        if "rounded_hours" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN rounded_hours TEXT NOT NULL DEFAULT '0.00'")
        if "elapsed_minutes" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN elapsed_minutes INTEGER NOT NULL DEFAULT 0")
            conn.exec_driver_sql("UPDATE entries SET elapsed_minutes = COALESCE(elapsed_minutes, 0)")
        if "invoice_number" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN invoice_number TEXT")
            cols2 = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(entries)").all()}
            if "invoice" in cols2:
                try:
                    conn.exec_driver_sql("UPDATE entries SET invoice_number = invoice WHERE invoice_number IS NULL")
                except Exception:
                    pass
        if "created_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE entries ADD COLUMN created_at TEXT")

migrate_schema()

# ---------- Roster lookup (client -> client_key) ----------
_ROSTER_MAP: Dict[str, str] = {}

def _load_roster() -> Dict[str, str]:
    paths = [
        BASE_DIR / "roster.json",
        BASE_DIR / "app" / "roster.json",
        DATA_DIR / "roster.json",
    ]
    for p in paths:
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                mapping: Dict[str, str] = {}
                if isinstance(raw, dict) and "clients" in raw and isinstance(raw["clients"], list):
                    for item in raw["clients"]:
                        if isinstance(item, dict) and "name" in item and "key" in item:
                            mapping[item["name"].strip().lower()] = str(item["key"]).strip()
                elif isinstance(raw, dict):
                    for name, key in raw.items():
                        mapping[str(name).strip().lower()] = str(key).strip()
                return mapping
            except Exception:
                return {}
    return {}

def lookup_key_for_client(client_name: str) -> Optional[str]:
    if not client_name:
        return None
    return _ROSTER_MAP.get(client_name.strip().lower()) or None

_ROSTER_MAP = _load_roster()

# ---------- Clients table JSON (client_table.json) ----------
def _client_table_path() -> Path:
    # prefer project root; fallbacks are app/ and data/
    for p in [BASE_DIR / "client_table.json", BASE_DIR / "app" / "client_table.json", DATA_DIR / "client_table.json"]:
        if p.exists():
            return p
    # default to project root if not present yet
    return BASE_DIR / "client_table.json"

def load_clients_json() -> Dict[str, Dict[str, Any]]:
    p = _client_table_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # enforce dict[str, dict]
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                out[str(k)] = v if isinstance(v, dict) else {"value": v}
        return out
    except Exception:
        return {}

def save_clients_json(payload: Dict[str, Dict[str, Any]]) -> None:
    p = _client_table_path()
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

# ---------- Helpers ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

API_TOKEN = os.environ.get("API_TOKEN", "").strip()

def require_token(authorization: str = Header("")):
    token = authorization.split()[-1] if authorization else ""
    if not API_TOKEN or token == API_TOKEN:
        return True
    raise HTTPException(401, "Unauthorized")

def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(CENTRAL)

def now_local() -> datetime:
    return datetime.now(tz=CENTRAL)

def safe_client_key(client: str) -> str:
    return re.sub(r"[^a-z0-9\-]+", "-", client.lower()).strip("-")

def compute_minutes(start: datetime, end: datetime) -> tuple[int, int, str]:
    mins = int((end - start).total_seconds() // 60)
    rounded = max(0, int(round(mins / 15.0) * 15))
    hrs = f"{(rounded/60.0):.2f}"
    return mins, rounded, hrs

# ---------- Jinja filters (m/d/yy HH:MM am/pm) ----------
def fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        dt = parse_iso(s)
        try:
            return dt.strftime("%-m/%-d/%y %I:%M %p")
        except ValueError:
            return dt.strftime("%#m/%#d/%y %#I:%M %p")
    except Exception:
        return "—"

templates.env.filters["fmt_dt"] = fmt_dt
templates.env.filters["hours2d"] = lambda s: f"{(float(s) if s else 0):.2f}"

# ---------- Pydantic models ----------
class PatchEntry(BaseModel):
    completed: Optional[bool] = None
    invoice_number: Optional[str] = None
    note: Optional[str] = None

class SessionStart(BaseModel):
    client: str
    client_key: Optional[str] = None
    note: Optional[str] = None

class SessionStop(BaseModel):
    client: str
    client_key: Optional[str] = None
    note: Optional[str] = None

# ---------- Query helpers ----------
def _fetch_rows(db: Session,
                client: str | None, client_key: str | None,
                status: str | None, qtext: str | None,
                since: str | None, until: str | None,
                sort: str, limit: int):
    qry = db.query(Entry)
    if client: qry = qry.filter(Entry.client == client)
    if client_key: qry = qry.filter(Entry.client_key == client_key)
    if status == "open": qry = qry.filter(Entry.completed == 0)
    if status == "done": qry = qry.filter(Entry.completed == 1)
    if qtext:
        like = f"%{qtext}%"
        qry = qry.filter(or_(Entry.client.like(like),
                             Entry.client_key.like(like),
                             Entry.note.like(like),
                             Entry.invoice_number.like(like)))
    def _to_date(s: str) -> Optional[date]:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None
    sdate = _to_date(since) if since else None
    udate = _to_date(until) if until else None

    rows = qry.order_by(Entry.id.desc()).limit(limit * 5).all()
    out: list[Entry] = []
    for r in rows:
        d = parse_iso(r.start_iso).date()
        if sdate and d < sdate: continue
        if udate and d > udate: continue
        out.append(r)

    if sort == "id_asc":
        out.sort(key=lambda r: r.id)
    elif sort == "start_asc":
        out.sort(key=lambda r: r.start_iso)
    elif sort == "start_desc":
        out.sort(key=lambda r: r.start_iso, reverse=True)
    else:  # "open_first_newest"
        out.sort(key=lambda r: (r.completed, -r.id))
    return out[:limit]

# ---------- UI ----------
@app.get("/", response_class=HTMLResponse)
def ui_index(request: Request,
             client: str | None = None,
             client_key: str | None = None,
             status: str | None = Query(None, pattern="^(open|done)$"),
             q: str | None = None,
             since: str | None = None,
             until: str | None = None,
             sort: str = "open_first_newest",
             limit: int = 500,
             db: Session = Depends(get_db)):
    rows = _fetch_rows(db, client, client_key, status, q, since, until, sort, limit)
    ctx = {"request": request, "rows": rows, "sort": sort,
           "client": client, "client_key": client_key, "status": status,
           "q": q, "since": since, "until": until, "limit": limit}
    return templates.TemplateResponse("index.html", ctx)

@app.get("/ui/table", response_class=HTMLResponse)
def ui_table(request: Request,
             client: str | None = None,
             client_key: str | None = None,
             status: str | None = Query(None, pattern="^(open|done)$"),
             q: str | None = None,
             since: str | None = None,
             until: str | None = None,
             sort: str = "open_first_newest",
             limit: int = 500,
             db: Session = Depends(get_db)):
    rows = _fetch_rows(db, client, client_key, status, q, since, until, sort, limit)
    return templates.TemplateResponse("_rows.html", {"request": request, "rows": rows})

# ---------- UI: Clients page ----------
@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    return templates.TemplateResponse("clients.html", {"request": request})

# ---------- UI actions ----------
@app.post("/ui/entries/{entry_id}/toggle-completed", response_class=HTMLResponse)
def ui_toggle_completed(entry_id: int, db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r: raise HTTPException(404, "Not found")
    r.completed = 0 if r.completed else 1
    db.commit(); db.refresh(r)
    return templates.TemplateResponse("_rows.html", {"request": {}, "rows": [r]})

@app.post("/ui/entries/{entry_id}/set-invoice", response_class=HTMLResponse)
def ui_set_invoice(entry_id: int, invoice_number: str = Form(""), db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r: raise HTTPException(404, "Not found")
    r.invoice_number = (invoice_number or "").strip() or None
    db.commit(); db.refresh(r)
    return templates.TemplateResponse("_rows.html", {"request": {}, "rows": [r]})

@app.post("/ui/entries/{entry_id}/delete", response_class=HTMLResponse)
def ui_delete_entry(entry_id: int, db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r: raise HTTPException(404, "Not found")
    db.delete(r); db.commit()
    return HTMLResponse("")

# ---------- Manual add & CSV import ----------
@app.post("/ui/manual")
def ui_manual(client: str = Form(...), client_key: str | None = Form(None),
              date_str: str = Form(...), start_str: str = Form(...), end_str: str = Form(...),
              note: str = Form(""), db: Session = Depends(get_db)):
    ck = (client_key or lookup_key_for_client(client) or safe_client_key(client))
    def parse_date_mdy(s: str) -> date:
        t = s.strip()
        for fmt in ("%m/%d/%Y", "%-m/%-d/%Y", "%m/%d/%y"):
            try: return datetime.strptime(t, fmt).date()
            except ValueError: pass
        raise HTTPException(400, "Invalid date; use mm/dd/yyyy")
    def parse_time_flexible(s: str) -> time:
        t = s.strip()
        for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M", "%H%M", "%H"):
            try: return datetime.strptime(t.replace(" ", ""), fmt.replace(" ", "")).time()
            except ValueError: pass
        for fmt in ("%I:%M %p", "%I %p"):
            try: return datetime.strptime(t, fmt).time()
            except ValueError: pass
        raise HTTPException(400, "Invalid time; e.g. 4:30 PM, 4 PM, 16:30")
    d = parse_date_mdy(date_str)
    t1 = parse_time_flexible(start_str)
    t2 = parse_time_flexible(end_str)
    sdt = datetime.combine(d, t1).replace(tzinfo=CENTRAL)
    edt = datetime.combine(d, t2).replace(tzinfo=CENTRAL)
    if edt <= sdt: edt += timedelta(days=1)

    mins, rmin, rhrs = compute_minutes(sdt, edt)
    r = Entry(client=client, client_key=ck, start_iso=sdt.isoformat(), end_iso=edt.isoformat(),
              minutes=mins, rounded_minutes=rmin, rounded_hours=rhrs, elapsed_minutes=mins,
              note=note or "", completed=0, created_at=now_local().isoformat())
    with SessionLocal() as s:
        s.add(r); s.commit()
    return RedirectResponse(url="/", status_code=302)

@app.post("/ui/import")
async def ui_import(csvfile: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await csvfile.read()
    text = content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        client = row.get("client") or row.get("Client") or ""
        if not client:
            continue
        roster_key = lookup_key_for_client(client)
        client_key = row.get("client_key") or row.get("Client Key") or roster_key or safe_client_key(client)
        start_iso = row.get("start_iso") or row.get("Start ISO") or now_local().isoformat()
        end_iso = row.get("end_iso") or row.get("End ISO") or None
        note = row.get("note") or row.get("Note") or ""
        completed = int(row.get("completed") or row.get("Completed") or 0)
        invoice = row.get("invoice_number") or row.get("Invoice") or None
        r = Entry(client=client, client_key=client_key, start_iso=start_iso, end_iso=end_iso,
                  note=note, completed=completed, invoice_number=invoice)
        try:
            if end_iso:
                sdt, edt = parse_iso(start_iso), parse_iso(end_iso)
                mins, rmin, rhrs = compute_minutes(sdt, edt)
                r.minutes, r.rounded_minutes, r.rounded_hours = mins, rmin, rhrs
                r.elapsed_minutes = mins
            else:
                r.minutes, r.rounded_minutes, r.rounded_hours = 0, 0, "0.00"
                r.elapsed_minutes = 0
        except Exception:
            r.minutes, r.rounded_minutes, r.rounded_hours = 0, 0, "0.00"
            r.elapsed_minutes = 0
        db.add(r)
    db.commit()
    return RedirectResponse(url="/", status_code=302)

# ---------- CSV Export ----------
@app.get("/api/export.csv")
def export_csv(client: str | None = None, client_key: str | None = None,
               completed: str | None = None, since: str | None = None, until: str | None = None,
               q: str | None = None, sort: str = "open_first_newest", limit: int = 500,
               db: Session = Depends(get_db)):
    status = None
    if completed == "0": status = "open"
    if completed == "1": status = "done"
    rows = _fetch_rows(db, client, client_key, status, q, since, until, sort, limit)

    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(["id","client","client_key","start_iso","end_iso","minutes","rounded_minutes","rounded_hours","note","completed","invoice_number","created_at"])
    for r in rows:
        w.writerow([r.id, r.client, r.client_key, r.start_iso, r.end_iso, r.minutes, r.rounded_minutes, r.rounded_hours, r.note or "", r.completed, r.invoice_number or "", r.created_at])
    text = buf.getvalue()
    resp = Response(text, media_type="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=tracker-export.csv"
    return resp

# ---------- JSON API: patch single entry ----------
@app.patch("/api/entries/{entry_id}", dependencies=[Depends(require_token)])
def patch_entry(entry_id: int, payload: PatchEntry, db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r: raise HTTPException(404, "Not found")
    if payload.completed is not None:
        r.completed = 1 if payload.completed else 0
    if payload.invoice_number is not None:
        r.invoice_number = payload.invoice_number.strip() or None
    if payload.note is not None and payload.note.strip():
        r.note = payload.note.strip()
    db.commit(); db.refresh(r)
    return {k: getattr(r, k) for k in r.__table__.columns.keys()}
	
# ---------- JSON API: get single entry (UI helper) ----------
@app.get("/api/entries/{entry_id}", response_class=JSONResponse)
def get_entry(entry_id: int, db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r:
        raise HTTPException(404, "Not found")
    return {k: getattr(r, k) for k in r.__table__.columns.keys()}

# ---------- UI: edit entry from modal ----------
@app.post("/ui/entries/{entry_id}/edit")
def ui_edit_entry(entry_id: int,
                  client: str = Form(...),
                  client_key: str = Form(...),
                  start_iso: str = Form(...),
                  end_iso: str | None = Form(None),
                  note: str = Form(""),
                  invoice_number: str | None = Form(None),
                  completed: str | None = Form(None),
                  db: Session = Depends(get_db)):
    r = db.get(Entry, entry_id)
    if not r:
        raise HTTPException(404, "Not found")

    r.client = client.strip()
    r.client_key = client_key.strip()
    r.start_iso = start_iso.strip()
    r.end_iso = (end_iso or "").strip() or None
    r.note = (note or "").strip()
    r.invoice_number = (invoice_number or "").strip() or None
    r.completed = 1 if (completed and completed not in ("0","false","False")) else 0

    # recompute minutes if both timestamps are present
    try:
        if r.start_iso and r.end_iso:
            sdt = parse_iso(r.start_iso)
            edt = parse_iso(r.end_iso)
            mins, rmin, rhrs = compute_minutes(sdt, edt)
            r.minutes, r.rounded_minutes, r.rounded_hours = mins, rmin, rhrs
            r.elapsed_minutes = mins
    except Exception:
        pass

    db.commit()
    return HTMLResponse("OK")

# ---------- Sessions API ----------
@app.post("/api/sessions/start", dependencies=[Depends(require_token)])
def api_sessions_start(payload: SessionStart, db: Session = Depends(get_db)) -> Dict[str, Any]:
    client = payload.client.strip()
    if not client:
        raise HTTPException(400, "client is required")
    derived_key = lookup_key_for_client(client)
    client_key = (payload.client_key or derived_key or safe_client_key(client)).strip()
    note = (payload.note or "").strip()

    r = Entry(
        client=client,
        client_key=client_key,
        start_iso=now_local().isoformat(),
        end_iso=None,
        minutes=0,
        rounded_minutes=0,
        rounded_hours="0.00",
        elapsed_minutes=0,
        note=note,
        completed=0,
        created_at=now_local().isoformat(),
    )
    db.add(r); db.commit(); db.refresh(r)
    return {"status": "started", "entry_id": r.id, "client": r.client, "client_key": r.client_key, "start_iso": r.start_iso}

@app.post("/api/sessions/stop", dependencies=[Depends(require_token)])
def api_sessions_stop(payload: SessionStop, db: Session = Depends(get_db)) -> Dict[str, Any]:
    client = payload.client.strip()
    if not client:
        raise HTTPException(400, "client is required")
    derived_key = lookup_key_for_client(client)
    client_key = payload.client_key or derived_key

    q = db.query(Entry).filter(Entry.client == client, Entry.end_iso.is_(None))
    if client_key:
        q = q.filter(Entry.client_key == client_key)
    r = q.order_by(desc(Entry.id)).first()
    if not r:
        raise HTTPException(404, "No active session to stop")

    end = now_local()
    sdt = parse_iso(r.start_iso)
    r.end_iso = end.isoformat()
    mins, rmin, rhrs = compute_minutes(sdt, end)
    r.minutes, r.rounded_minutes, r.rounded_hours = mins, rmin, rhrs
    r.elapsed_minutes = mins
    if payload.note and payload.note.strip():
        r.note = (r.note + ("\n" if r.note else "") + payload.note.strip()) if r.note else payload.note.strip()
    db.commit(); db.refresh(r)

    return {
        "status": "stopped",
        "entry_id": r.id,
        "client": r.client,
        "client_key": r.client_key,
        "start_iso": r.start_iso,
        "end_iso": r.end_iso,
        "minutes": r.minutes,
        "rounded_minutes": r.rounded_minutes,
        "rounded_hours": r.rounded_hours,
        "note": r.note or "",
    }

@app.get("/api/sessions/active", dependencies=[Depends(require_token)])
def api_sessions_active(client: str | None = None, client_key: str | None = None,
                        db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    q = db.query(Entry).filter(Entry.end_iso.is_(None))
    if client:
        q = q.filter(Entry.client == client)
    if client_key:
        q = q.filter(Entry.client_key == client_key)
    rows = q.order_by(desc(Entry.id)).all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r.id,
            "client": r.client,
            "client_key": r.client_key,
            "start_iso": r.start_iso,
            "note": r.note or "",
            "created_at": r.created_at,
        })
    return out

# ---------- Clients JSON API ----------
@app.get("/api/clients", response_class=JSONResponse)
def api_clients_list():
    data = load_clients_json()
    # Build dynamic column set for UI convenience
    columns = set()
    for attrs in data.values():
        columns.update(attrs.keys())
    return {"clients": data, "columns": sorted(columns)}

@app.get("/api/clients/{client_name}", response_class=JSONResponse)
def api_clients_get(client_name: str):
    data = load_clients_json()
    if client_name not in data:
        raise HTTPException(404, "Client not found")
    return {"name": client_name, "attributes": data[client_name]}

@app.post("/api/clients/{client_name}", response_class=JSONResponse)
def api_clients_upsert(client_name: str, payload: Dict[str, Any]):
    data = load_clients_json()
    existing = data.get(client_name, {})
    if not isinstance(existing, dict):
        existing = {}
    # Merge/replace keys from payload
    for k, v in payload.items():
        existing[k] = v
    data[client_name] = existing
    save_clients_json(data)
    return {"ok": True, "name": client_name, "attributes": existing}

@app.post("/api/clients", response_class=JSONResponse)
def api_clients_create(payload: Dict[str, Any]):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name required")
    attrs = payload.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    data = load_clients_json()
    if name in data:
        raise HTTPException(409, "Client already exists")
    data[name] = attrs
    save_clients_json(data)
    return {"ok": True, "name": name, "attributes": attrs}

# ---------- Favicon ----------
@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)
