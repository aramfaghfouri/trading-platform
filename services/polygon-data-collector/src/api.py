"""
FastAPI endpoints for Polygon Data Collector Service
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import logging

from .main import PolygonDataService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Polygon Data Collector Service",
    description="A microservice for collecting and processing ticker data from Polygon.io",
    version="1.0.0"
)

# Initialize service
service = PolygonDataService()

# Pydantic models
class TickerRequest(BaseModel):
    tickers: List[str]
    days_back: Optional[int] = 30

class SearchRequest(BaseModel):
    search_term: str
    limit: Optional[int] = 50
    days_back: Optional[int] = 30

class TopTickersRequest(BaseModel):
    limit: Optional[int] = 100
    days_back: Optional[int] = 30

class CollectionResponse(BaseModel):
    success: bool
    message: str
    data_count: int
    tickers: List[str]

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        market_status = service.get_market_status()
        return {
            "status": "healthy",
            "service": "polygon-data-collector",
            "market_status": market_status
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Collect data for specific tickers
@app.post("/collect", response_model=CollectionResponse)
async def collect_ticker_data(request: TickerRequest, background_tasks: BackgroundTasks):
    """Collect data for specific tickers"""
    try:
        logger.info(f"Collecting data for tickers: {request.tickers}")
        
        # Run collection in background
        data = await service.collect_ticker_data(request.tickers, request.days_back)
        
        return CollectionResponse(
            success=True,
            message=f"Successfully collected data for {len(data)} tickers",
            data_count=len(data),
            tickers=request.tickers
        )
        
    except Exception as e:
        logger.error(f"Failed to collect ticker data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Search and collect data
@app.post("/search", response_model=CollectionResponse)
async def search_and_collect(request: SearchRequest, background_tasks: BackgroundTasks):
    """Search for tickers and collect data"""
    try:
        logger.info(f"Searching for tickers with term: {request.search_term}")
        
        data = await service.search_and_collect(
            request.search_term, 
            request.limit, 
            request.days_back
        )
        
        tickers = [item['ticker'] for item in data]
        
        return CollectionResponse(
            success=True,
            message=f"Successfully collected data for {len(data)} tickers",
            data_count=len(data),
            tickers=tickers
        )
        
    except Exception as e:
        logger.error(f"Failed to search and collect data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Collect top tickers
@app.post("/top", response_model=CollectionResponse)
async def collect_top_tickers(request: TopTickersRequest, background_tasks: BackgroundTasks):
    """Collect data for top tickers by volume"""
    try:
        logger.info(f"Collecting data for top {request.limit} tickers")
        
        data = await service.collect_top_tickers(request.limit, request.days_back)
        
        tickers = [item['ticker'] for item in data]
        
        return CollectionResponse(
            success=True,
            message=f"Successfully collected data for {len(data)} top tickers",
            data_count=len(data),
            tickers=tickers
        )
        
    except Exception as e:
        logger.error(f"Failed to collect top tickers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Get market status
@app.get("/status")
async def get_market_status():
    """Get current market status"""
    try:
        status = service.get_market_status()
        return {"market_status": status}
    except Exception as e:
        logger.error(f"Failed to get market status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Generate report
@app.post("/report")
async def generate_report(data: List[Dict[str, Any]]):
    """Generate analysis report for collected data"""
    try:
        report = service.generate_report(data)
        return {"report": report}
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Get service metrics
@app.get("/metrics")
async def get_metrics():
    """Get service metrics"""
    try:
        # This would typically come from a metrics collector
        return {
            "service": "polygon-data-collector",
            "uptime": "N/A",  # Would be calculated from start time
            "requests_processed": 0,  # Would be tracked
            "data_points_collected": 0  # Would be tracked
        }
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
