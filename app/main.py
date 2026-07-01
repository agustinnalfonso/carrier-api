from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import create_engine, Column, String, Numeric, Integer, Text, DateTime, cast
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import os
from dotenv import load_dotenv
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import Boolean, func
from sqlalchemy.dialects.postgresql import insert as pg_insert


load_dotenv()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class Load(Base):
    __tablename__ = "loads"
    load_id           = Column(String(20), primary_key=True)
    origin            = Column(String(100), nullable=False)
    destination       = Column(String(100), nullable=False)
    pickup_datetime   = Column(DateTime, nullable=False)
    delivery_datetime = Column(DateTime, nullable=False)
    equipment_type    = Column(String(50), nullable=False)
    loadboard_rate    = Column(Numeric(10, 2), nullable=False)
    notes             = Column(Text)
    weight            = Column(Numeric(10, 2))
    commodity_type    = Column(String(100))
    num_of_pieces     = Column(Integer)
    miles             = Column(Numeric(10, 2))
    dimensions        = Column(String(100))
    status            = Column(String(20), default="available")

class Call(Base):
    __tablename__ = "calls"
    id                     = Column(Integer, primary_key=True, autoincrement=True)
    call_id                = Column(String(100), unique=True, nullable=False)
    run_id                 = Column(String(100))
    call_duration_seconds  = Column(Numeric(10, 2))
    mc_number              = Column(String(20))
    carrier_name           = Column(String(200))
    carrier_eligible       = Column(Boolean)
    load_id                = Column(String(20))
    origin                 = Column(String(100))
    destination            = Column(String(100))
    equipment_type         = Column(String(50))
    loadboard_rate         = Column(Numeric(10, 2))
    carrier_first_offer    = Column(Numeric(10, 2))
    final_agreed_rate      = Column(Numeric(10, 2))
    negotiation_rounds     = Column(Integer)
    decline_reason         = Column(Text)
    outcome                = Column(String(50))
    outcome_reason         = Column(Text)
    sentiment              = Column(String(50))
    sentiment_reason       = Column(Text)
    created_at             = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class LoadOut(BaseModel):
    load_id: str
    origin: str
    destination: str
    pickup_datetime: datetime
    delivery_datetime: datetime
    equipment_type: str
    loadboard_rate: float
    notes: Optional[str] = None
    weight: Optional[float] = None
    commodity_type: Optional[str] = None
    num_of_pieces: Optional[int] = None
    miles: Optional[float] = None
    dimensions: Optional[str] = None
    status: Optional[str] = None


class CallIn(BaseModel):
    call_id: str
    run_id: Optional[str] = None
    call_duration_seconds: Optional[float] = None
    mc_number: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_eligible: Optional[bool] = None
    load_id: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    equipment_type: Optional[str] = None
    loadboard_rate: Optional[float] = None
    carrier_first_offer: Optional[float] = None
    final_agreed_rate: Optional[float] = None
    negotiation_rounds: Optional[int] = None
    decline_reason: Optional[str] = None
    outcome: Optional[str] = None
    outcome_reason: Optional[str] = None
    sentiment: Optional[str] = None
    sentiment_reason: Optional[str] = None
    
    class Config:
        from_attributes = True

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
API_KEY = os.getenv("API_KEY", "changeme")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def require_api_key(key: str = Depends(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Carrier Load Search API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/search-loads", response_model=list[LoadOut])
def search_loads(
    load_id: Optional[str]        = Query(None, description="Exact load ID, e.g. LD-1003"),
    origin: Optional[str]         = Query(None, description="Origin city or state, e.g. Chicago or IL"),
    destination: Optional[str]    = Query(None, description="Destination city or state, e.g. Dallas or TX"),
    equipment_type: Optional[str] = Query(None, description="e.g. Dry Van, Reefer, Flatbed"),
    commodity_type: Optional[str] = Query(None, description="Type of goods, e.g. produce, steel, electronics"),
    pickup_date: Optional[str]    = Query(None, description="Pickup date, e.g. 2025-07-01"),
    max_weight: Optional[float]   = Query(None, description="Max load weight in lbs"),
    min_rate: Optional[float]     = Query(None, description="Minimum rate in USD"),
    max_rate: Optional[float]     = Query(None, description="Maximum rate in USD"),
    limit: int                    = Query(3, le=10),
    db: Session                   = Depends(get_db),
    _: str                        = Depends(require_api_key),
):
    # If load_id provided, return that specific load directly
    if load_id:
        load = db.query(Load).filter(Load.load_id == load_id.upper()).first()
        if not load:
            raise HTTPException(status_code=404, detail=f"Load {load_id} not found")
        return [load]

    query = db.query(Load).filter(Load.status == "available")

    if origin:
        query = query.filter(Load.origin.ilike(f"%{origin}%"))

    if destination:
        query = query.filter(Load.destination.ilike(f"%{destination}%"))

    if equipment_type:
        query = query.filter(Load.equipment_type.ilike(f"%{equipment_type}%"))

    if commodity_type:
        query = query.filter(Load.commodity_type.ilike(f"%{commodity_type}%"))

    if pickup_date:
        query = query.filter(cast(Load.pickup_datetime, String).like(f"{pickup_date}%"))

    if max_weight:
        query = query.filter(Load.weight <= max_weight)

    if min_rate:
        query = query.filter(Load.loadboard_rate >= min_rate)

    if max_rate:
        query = query.filter(Load.loadboard_rate <= max_rate)

    results = query.order_by(Load.pickup_datetime).limit(limit).all()

    if not results:
        raise HTTPException(status_code=404, detail="No available loads found for those parameters")

    return results

@app.post("/calls", status_code=201)
def store_call(
    payload: CallIn,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    data = payload.model_dump()
    stmt = pg_insert(Call).values(**data)
    update_cols = {c: stmt.excluded[c] for c in data if c != "call_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["call_id"], set_=update_cols)
    db.execute(stmt)
    db.commit()
    return {"status": "ok", "call_id": payload.call_id}


@app.get("/metrics")
def get_metrics(
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    total_calls = db.query(func.count(Call.id)).scalar() or 0

    outcome_counts = dict(
        db.query(Call.outcome, func.count(Call.id))
        .group_by(Call.outcome)
        .all()
    )

    sentiment_counts = dict(
        db.query(Call.sentiment, func.count(Call.id))
        .group_by(Call.sentiment)
        .all()
    )

    booked_calls = outcome_counts.get("Booked", 0)
    booking_rate = round((booked_calls / total_calls) * 100, 1) if total_calls else 0

    ineligible_calls = (
        db.query(func.count(Call.id)).filter(Call.carrier_eligible == False).scalar() or 0
    )
    eligibility_rate = (
        round(((total_calls - ineligible_calls) / total_calls) * 100, 1) if total_calls else 0
    )

    avg_duration = db.query(func.avg(Call.call_duration_seconds)).scalar()
    avg_negotiation_rounds = db.query(func.avg(Call.negotiation_rounds)).scalar()
    avg_loadboard_rate = db.query(func.avg(Call.loadboard_rate)).scalar()
    avg_final_rate = (
        db.query(func.avg(Call.final_agreed_rate))
        .filter(Call.final_agreed_rate.isnot(None))
        .scalar()
    )

    decline_reasons = dict(
        db.query(Call.decline_reason, func.count(Call.id))
        .filter(Call.decline_reason.isnot(None))
        .group_by(Call.decline_reason)
        .all()
    )

    return {
        "total_calls": total_calls,
        "booking_rate_pct": booking_rate,
        "eligibility_rate_pct": eligibility_rate,
        "outcome_breakdown": outcome_counts,
        "sentiment_breakdown": sentiment_counts,
        "avg_call_duration_seconds": float(avg_duration) if avg_duration else None,
        "avg_negotiation_rounds": float(avg_negotiation_rounds) if avg_negotiation_rounds else None,
        "avg_loadboard_rate": float(avg_loadboard_rate) if avg_loadboard_rate else None,
        "avg_final_agreed_rate": float(avg_final_rate) if avg_final_rate else None,
        "decline_reasons": decline_reasons,
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return FileResponse("app/dashboard.html")

@app.get("/health")
def health():
    return {"status": "ok"}
