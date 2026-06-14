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


@app.get("/health")
def health():
    return {"status": "ok"}
