import os, sqlite3, hashlib, hmac, base64, json, time, secrets, shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
UPLOADS = DATA / "uploads"
DATA.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)
DB = DATA / "collab.db"
SECRET = os.getenv("APP_SECRET", "change-this-secret-before-deployment").encode()
app = FastAPI(title="CloudCollab Demo", description="Cloud-based remote work collaboration prototype")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, salt TEXT, password_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, name TEXT, owner_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memberships(user_id INTEGER, team_id INTEGER, role TEXT DEFAULT 'member', UNIQUE(user_id, team_id));
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, team_id INTEGER, uploader_id INTEGER, original_name TEXT, stored_name TEXT, size INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, team_id INTEGER, user_id INTEGER, action TEXT, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
init_db()

def pw_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()

def make_token(uid):
    payload = base64.urlsafe_b64encode(json.dumps({"uid": uid, "exp": int(time.time()) + 86400}).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please log in")
    token = authorization[7:]
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < int(time.time()):
            raise ValueError()
        with conn() as c:
            user = c.execute("SELECT id, username FROM users WHERE id=?", (data["uid"],)).fetchone()
        if not user: raise ValueError()
        return dict(user)
    except Exception:
        raise HTTPException(401, "Session expired or invalid; please log in again")

def log_activity(team_id, user_id, action, detail):
    with conn() as c:
        c.execute("INSERT INTO activity(team_id,user_id,action,detail) VALUES(?,?,?,?)",
                  (team_id, user_id, action, detail[:250]))

def ensure_member(team_id, uid):
    with conn() as c:
        row = c.execute("SELECT role FROM memberships WHERE team_id=? AND user_id=?", (team_id, uid)).fetchone()
    if not row: raise HTTPException(403, "You are not a member of this team")
    return row["role"]

class Credentials(BaseModel):
    username: str
    password: str

class TeamCreate(BaseModel):
    name: str

class JoinTeam(BaseModel):
    team_id: int

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"status":"ok", "service":"CloudCollab", "storage":"SQLite + local volume"}

@app.post("/api/register")
def register(body: Credentials):
    username = body.username.strip()
    if len(username) < 3 or len(username) > 32 or not username.replace("_","").isalnum():
        raise HTTPException(400, "Username must be 3-32 characters (letters, numbers, underscore)")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must contain at least 8 characters")
    salt = secrets.token_hex(16)
    try:
        with conn() as c:
            cur = c.execute("INSERT INTO users(username,salt,password_hash) VALUES(?,?,?)",
                            (username, salt, pw_hash(body.password, salt)))
            uid = cur.lastrowid
            cur = c.execute("INSERT INTO teams(name,owner_id) VALUES(?,?)", (f"{username}'s Team", uid))
            tid = cur.lastrowid
            c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,?)", (uid, tid, "admin"))
        log_activity(tid, uid, "Account created", f"{username} created an account and team")
        return {"token": make_token(uid), "user":{"id":uid,"username":username}}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")

@app.post("/api/login")
def login(body: Credentials):
    with conn() as c:
        user = c.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    if not user or not hmac.compare_digest(pw_hash(body.password, user["salt"]), user["password_hash"]):
        raise HTTPException(401, "Incorrect username or password")
    return {"token": make_token(user["id"]), "user":{"id":user["id"],"username":user["username"]}}

@app.get("/api/me")
def me(user=Depends(current_user)):
    return user

@app.get("/api/teams")
def teams(user=Depends(current_user)):
    with conn() as c:
        rows = c.execute("""SELECT t.id,t.name,m.role,t.created_at FROM teams t
        JOIN memberships m ON m.team_id=t.id WHERE m.user_id=? ORDER BY t.id DESC""", (user["id"],)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/teams")
def create_team(body: TeamCreate, user=Depends(current_user)):
    name = body.name.strip()
    if len(name) < 2 or len(name) > 80: raise HTTPException(400, "Team name must be 2-80 characters")
    with conn() as c:
        cur = c.execute("INSERT INTO teams(name,owner_id) VALUES(?,?)", (name, user["id"]))
        tid = cur.lastrowid
        c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,?)", (user["id"],tid,"admin"))
    log_activity(tid, user["id"], "Team created", name)
    return {"id":tid,"name":name,"role":"admin"}

@app.post("/api/teams/join")
def join_team(body: JoinTeam, user=Depends(current_user)):
    with conn() as c:
        team = c.execute("SELECT id,name FROM teams WHERE id=?", (body.team_id,)).fetchone()
        if not team: raise HTTPException(404, "Team not found")
        existing = c.execute("SELECT 1 FROM memberships WHERE team_id=? AND user_id=?", (body.team_id,user["id"])).fetchone()
        if existing: return {"message":"Already a member"}
        c.execute("INSERT INTO memberships(user_id,team_id,role) VALUES(?,?,?)", (user["id"],body.team_id,"member"))
    log_activity(body.team_id, user["id"], "Member joined", user["username"])
    return {"message":f"Joined {team['name']}"}

@app.get("/api/teams/{team_id}/members")
def members(team_id: int, user=Depends(current_user)):
    ensure_member(team_id, user["id"])
    with conn() as c:
        rows = c.execute("""SELECT u.id,u.username,m.role,m.rowid AS member_row FROM users u
        JOIN memberships m ON m.user_id=u.id WHERE m.team_id=? ORDER BY m.role DESC,u.username""", (team_id,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/teams/{team_id}/files")
def list_files(team_id: int, user=Depends(current_user)):
    ensure_member(team_id, user["id"])
    with conn() as c:
        rows = c.execute("""SELECT f.id,f.original_name,f.size,f.created_at,u.username AS uploaded_by
        FROM files f JOIN users u ON u.id=f.uploader_id WHERE f.team_id=? ORDER BY f.id DESC""", (team_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/teams/{team_id}/files")
async def upload_file(team_id: int, file: UploadFile = File(...), user=Depends(current_user)):
    ensure_member(team_id, user["id"])
    name = Path(file.filename or "upload.bin").name
    if not name or len(name) > 180: raise HTTPException(400, "Invalid file name")
    stored = secrets.token_hex(16) + Path(name).suffix[:12]
    dest = UPLOADS / stored
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            size += len(chunk)
            if size > 20 * 1024 * 1024:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "Maximum file size is 20 MB")
            out.write(chunk)
    with conn() as c:
        c.execute("INSERT INTO files(team_id,uploader_id,original_name,stored_name,size) VALUES(?,?,?,?,?)",
                  (team_id,user["id"],name,stored,size))
    log_activity(team_id, user["id"], "File uploaded", name)
    return {"message":"Uploaded successfully","name":name,"size":size}

@app.get("/api/teams/{team_id}/files/{file_id}/download")
def download_file(team_id: int, file_id: int, user=Depends(current_user)):
    ensure_member(team_id, user["id"])
    with conn() as c:
        row = c.execute("SELECT * FROM files WHERE id=? AND team_id=?", (file_id,team_id)).fetchone()
    if not row: raise HTTPException(404, "File not found")
    log_activity(team_id, user["id"], "File downloaded", row["original_name"])
    return FileResponse(UPLOADS / row["stored_name"], filename=row["original_name"])

@app.get("/api/teams/{team_id}/activity")
def activity(team_id: int, user=Depends(current_user)):
    ensure_member(team_id, user["id"])
    with conn() as c:
        rows = c.execute("""SELECT a.id,a.action,a.detail,a.created_at,u.username
        FROM activity a JOIN users u ON u.id=a.user_id WHERE a.team_id=? ORDER BY a.id DESC LIMIT 100""", (team_id,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/teams/discover")
def discover(user=Depends(current_user)):
    with conn() as c:
        rows = c.execute("""SELECT t.id,t.name,COUNT(m.user_id) AS members FROM teams t
        LEFT JOIN memberships m ON m.team_id=t.id
        WHERE t.owner_id != ? AND t.id NOT IN (SELECT team_id FROM memberships WHERE user_id=?)
        GROUP BY t.id ORDER BY t.id DESC LIMIT 50""", (user["id"],user["id"])).fetchall()
    return [dict(r) for r in rows]
