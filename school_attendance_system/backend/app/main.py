import os, math
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlmodel import SQLModel, Field, Session, create_engine, select

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE, 'school.db')}")
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
SECRET = os.getenv("JWT_SECRET", "DEV-ONLY-change-this-secret-before-deployment")
ALGORITHM = "HS256"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token")

app = FastAPI(title="School Attendance API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:8000").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    display_name: str
    role: str = "student"
    active: bool = True

class Building(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    latitude: float
    longitude: float
    radius_m: int = 80
    active: bool = True

class ClassSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    building_id: int = Field(foreign_key="building.id")
    starts_at: datetime
    ends_at: datetime
    anomaly_z: float = 2.0
    min_samples: int = 5
    active: bool = True

class Attendance(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, foreign_key="classsession.id")
    student_id: int = Field(index=True, foreign_key="user.id")
    checked_in_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: Optional[datetime] = None
    inside_seconds: int = 0
    last_inside_at: Optional[datetime] = None
    is_inside: bool = False
    last_accuracy_m: Optional[float] = None
    location_permission_issue: bool = False
    UNIQUE_KEY: str = ""

def utcnow(): return datetime.now(timezone.utc)
def dist_m(lat1, lon1, lat2, lon2):
    r=6371000
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_db():
    with Session(engine) as s: yield s

def token_for(user):
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": utcnow()+timedelta(hours=10)}, SECRET, algorithm=ALGORITHM)

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)):
    try:
        payload=jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        user=db.get(User, int(payload["sub"]))
    except Exception:
        user=None
    if not user or not user.active: raise HTTPException(401, "인증이 필요합니다.")
    return user

def admin(user=Depends(current_user)):
    if user.role != "admin": raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user

@app.on_event("startup")
def startup():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        email=os.getenv("ADMIN_EMAIL", "admin@school.local")
        if not db.exec(select(User).where(User.email==email)).first():
            db.add(User(email=email, password_hash=pwd.hash(os.getenv("ADMIN_PASSWORD","ChangeMe-12345!")), display_name="학교 관리자", role="admin"))
            db.commit()

@app.get("/")
def home(): return FileResponse(os.path.join(BASE, "web", "index.html"))

@app.post("/auth/token")
def login(form: OAuth2PasswordRequestForm=Depends(), db: Session=Depends(get_db)):
    user=db.exec(select(User).where(User.email==form.username)).first()
    if not user or not pwd.verify(form.password, user.password_hash) or not user.active:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인하세요.")
    return {"access_token":token_for(user),"token_type":"bearer","role":user.role,"display_name":user.display_name}

@app.get("/me")
def me(user=Depends(current_user)):
    return {"id":user.id,"email":user.email,"display_name":user.display_name,"role":user.role}

@app.post("/admin/students")
def create_student(data: dict, db: Session=Depends(get_db), _: User=Depends(admin)):
    email=data.get("email","").strip().lower(); password=data.get("password","")
    if not email or len(password)<12: raise HTTPException(400,"이메일과 12자 이상의 임시 비밀번호가 필요합니다.")
    if db.exec(select(User).where(User.email==email)).first(): raise HTTPException(409,"이미 등록된 이메일입니다.")
    u=User(email=email,password_hash=pwd.hash(password),display_name=data.get("display_name","학생"),role="student")
    db.add(u); db.commit(); db.refresh(u)
    return {"id":u.id,"email":u.email,"display_name":u.display_name}

@app.post("/admin/buildings")
def create_building(data: dict, db: Session=Depends(get_db), _: User=Depends(admin)):
    b=Building(name=data["name"],latitude=float(data["latitude"]),longitude=float(data["longitude"]),radius_m=int(data.get("radius_m",80)))
    if not 10 <= b.radius_m <= 1000: raise HTTPException(400,"반경은 10~1000m로 설정하세요.")
    db.add(b); db.commit(); db.refresh(b); return b

@app.get("/admin/buildings")
def list_buildings(db: Session=Depends(get_db), _: User=Depends(admin)):
    return db.exec(select(Building)).all()

@app.post("/admin/sessions")
def create_class(data: dict, db: Session=Depends(get_db), _: User=Depends(admin)):
    if not db.get(Building,int(data["building_id"])): raise HTTPException(404,"건물을 찾을 수 없습니다.")
    start=datetime.fromisoformat(data["starts_at"].replace("Z","+00:00"))
    end=datetime.fromisoformat(data["ends_at"].replace("Z","+00:00"))
    if end<=start: raise HTTPException(400,"종료 시각은 시작 시각보다 뒤여야 합니다.")
    c=ClassSession(title=data["title"],building_id=int(data["building_id"]),starts_at=start,ends_at=end,
                   anomaly_z=float(data.get("anomaly_z",2)),min_samples=int(data.get("min_samples",5)))
    db.add(c); db.commit(); db.refresh(c); return c

@app.get("/admin/sessions")
def list_sessions(db: Session=Depends(get_db), _: User=Depends(admin)):
    return db.exec(select(ClassSession).order_by(ClassSession.id.desc())).all()

@app.post("/student/sessions/{session_id}/checkin")
def checkin(session_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    if user.role!="student": raise HTTPException(403,"학생 계정만 출석할 수 있습니다.")
    c=db.get(ClassSession,session_id)
    if not c or not c.active: raise HTTPException(404,"수업을 찾을 수 없습니다.")
    now=utcnow()
    if now<c.starts_at-timedelta(minutes=30) or now>c.ends_at: raise HTTPException(400,"출석 가능한 시간이 아닙니다.")
    old=db.exec(select(Attendance).where(Attendance.session_id==session_id,Attendance.student_id==user.id)).first()
    if old: return {"attendance_id":old.id,"message":"이미 출석 처리되었습니다."}
    a=Attendance(session_id=session_id,student_id=user.id,checked_in_at=now)
    db.add(a); db.commit(); db.refresh(a)
    return {"attendance_id":a.id,"message":"출석 체크 완료"}

@app.post("/student/attendance/{attendance_id}/location")
def location_ping(attendance_id:int,data:dict,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=db.get(Attendance,attendance_id)
    if not a or a.student_id!=user.id: raise HTTPException(404,"출석 기록을 찾을 수 없습니다.")
    c=db.get(ClassSession,a.session_id); b=db.get(Building,c.building_id)
    now=utcnow()
    if now>c.ends_at+timedelta(minutes=10): raise HTTPException(400,"수업 위치 측정 시간이 종료되었습니다.")
    lat=float(data["latitude"]); lon=float(data["longitude"]); acc=float(data.get("accuracy_m",999))
    if not (-90<=lat<=90 and -180<=lon<=180 and 0<acc<10000): raise HTTPException(400,"위치 값이 올바르지 않습니다.")
    # Accuracy is retained for review; low-quality fixes are not treated as definitive presence.
    inside=dist_m(lat,lon,b.latitude,b.longitude)<=b.radius_m and acc<=100
    if a.is_inside and a.last_seen_at:
        # Count the previous interval up to this fix, including the exit transition.
        # Cap gaps so a long offline period is not incorrectly counted as presence.
        delta=max(0,min(int((now-a.last_seen_at).total_seconds()),120))
        a.inside_seconds += delta
    a.is_inside=inside
    a.last_inside_at=now if inside else None
    a.last_seen_at=now; a.last_accuracy_m=acc
    db.add(a); db.commit()
    return {"accepted":True,"inside_geofence":inside,"accuracy_m":acc,"message":"위치 기록 수신"}

@app.post("/student/attendance/{attendance_id}/permission-issue")
def permission_issue(attendance_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=db.get(Attendance,attendance_id)
    if not a or a.student_id!=user.id: raise HTTPException(404,"출석 기록을 찾을 수 없습니다.")
    a.location_permission_issue=True; db.add(a); db.commit(); return {"ok":True}

@app.get("/student/sessions")
def student_sessions(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role!="student": raise HTTPException(403,"학생 계정만 이용할 수 있습니다.")
    now=utcnow()
    return db.exec(select(ClassSession).where(ClassSession.active==True,ClassSession.ends_at>=now).order_by(ClassSession.starts_at)).all()

@app.get("/admin/reports/{session_id}")
def report(session_id:int,db:Session=Depends(get_db),_:User=Depends(admin)):
    c=db.get(ClassSession,session_id)
    if not c: raise HTTPException(404,"수업을 찾을 수 없습니다.")
    rows=db.exec(select(Attendance).where(Attendance.session_id==session_id)).all()
    vals=[r.inside_seconds/60 for r in rows]
    mean=sum(vals)/len(vals) if vals else 0
    sd=(sum((x-mean)**2 for x in vals)/len(vals))**0.5 if vals else 0
    out=[]
    for a in rows:
        u=db.get(User,a.student_id); mins=a.inside_seconds/60
        z=abs(mins-mean)/sd if sd>0 else (0 if mins==mean else 999)
        candidate=len(vals)>=c.min_samples and z>=c.anomaly_z
        out.append({"student":u.display_name,"email":u.email,"minutes":round(mins,1),"last_seen_at":a.last_seen_at.isoformat() if a.last_seen_at else None,"accuracy_m":a.last_accuracy_m,"permission_issue":a.location_permission_issue,"anomaly_candidate":candidate,"z_score":round(z,2)})
    return {"session":c.title,"count":len(out),"mean_minutes":round(mean,1),"std_minutes":round(sd,1),"results":out}

@app.get("/health")
def health(): return {"ok":True}
