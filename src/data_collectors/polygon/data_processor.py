"""
Data Processor for Polygon Ticker Data
Processes and analyzes collected ticker data
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class TickerDataProcessor:
    def __init__(self):
        self.processed_data = {}
    
    def process_historical_data(self, ticker_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process historical data for analysis"""
        try:
            historical = ticker_data.get('historical_data', {})
            results = historical.get('results', [])
            
            if not results:
                return {}
            
            # Convert to DataFrame
            df = pd.DataFrame(results)
            df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Calculate technical indicators
            processed = {
                'ticker': ticker_data['ticker'],
                'data_points': len(df),
                'date_range': {
                    'start': df.index.min().strftime('%Y-%m-%d'),
                    'end': df.index.max().strftime('%Y-%m-%d')
                },
                'price_stats': {
                    'open': df['o'].iloc[-1] if len(df) > 0 else None,
                    'high': df['h'].max(),
                    'low': df['l'].min(),
                    'close': df['c'].iloc[-1] if len(df) > 0 else None,
                    'volume': df['v'].sum()
                },
                'volatility': self._calculate_volatility(df),
                'moving_averages': self._calculate_moving_averages(df),
                'price_change': self._calculate_price_change(df),
                'volume_analysis': self._analyze_volume(df)
            }
            
            return processed
            
        except Exception as e:
            logger.error(f"Failed to process historical data: {e}")
            return {}
    
    def _calculate_volatility(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate price volatility metrics"""
        if len(df) < 2:
            return {}
        
        returns = df['c'].pct_change().dropna()
        
        return {
            'daily_volatility': returns.std(),
            'annualized_volatility': returns.std() * np.sqrt(252),
            'max_drawdown': self._calculate_max_drawdown(df['c']),
            'sharpe_ratio': self._calculate_sharpe_ratio(returns)
        }
    
    def _calculate_moving_averages(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate moving averages"""
        if len(df) < 20:
            return {}
        
        return {
            'sma_5': df['c'].rolling(5).mean().iloc[-1],
            'sma_10': df['c'].rolling(10).mean().iloc[-1],
            'sma_20': df['c'].rolling(20).mean().iloc[-1],
            'ema_12': df['c'].ewm(span=12).mean().iloc[-1],
            'ema_26': df['c'].ewm(span=26).mean().iloc[-1]
        }
    
    def _calculate_price_change(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate price change metrics"""
        if len(df) < 2:
            return {}
        
        first_close = df['c'].iloc[0]
        last_close = df['c'].iloc[-1]
        
        return {
            'total_change': last_close - first_close,
            'total_change_pct': ((last_close - first_close) / first_close) * 100,
            'max_gain': df['c'].max() - first_close,
            'max_loss': df['c'].min() - first_close
        }
    
    def _analyze_volume(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze volume patterns"""
        if len(df) < 2:
            return {}
        
        return {
            'avg_volume': df['v'].mean(),
            'max_volume': df['v'].max(),
            'min_volume': df['v'].min(),
            'volume_trend': self._calculate_volume_trend(df['v'])
        }
    
    def _calculate_max_drawdown(self, prices: pd.Series) -> float:
        """Calculate maximum drawdown"""
        peak = prices.expanding().max()
        drawdown = (prices - peak) / peak
        return drawdown.min()
    
    def _calculate_sharpe_ratio(self, returns: pd.Series, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio"""
        if returns.std() == 0:
            return 0
        return (returns.mean() - risk_free_rate/252) / returns.std() * np.sqrt(252)
    
    def _calculate_volume_trend(self, volume: pd.Series) -> str:
        """Calculate volume trend"""
        if len(volume) < 5:
            return "insufficient_data"
        
        recent_avg = volume.tail(5).mean()
        earlier_avg = volume.head(5).mean()
        
        if recent_avg > earlier_avg * 1.1:
            return "increasing"
        elif recent_avg < earlier_avg * 0.9:
            return "decreasing"
        else:
            return "stable"
    
    def process_news_sentiment(self, ticker_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process news data for sentiment analysis"""
        try:
            news = ticker_data.get('news', [])
            
            if not news:
                return {}
            
            processed_news = {
                'ticker': ticker_data['ticker'],
                'total_articles': len(news),
                'recent_articles': []
            }
            
            for article in news[:5]:  # Process last 5 articles
                processed_news['recent_articles'].append({
                    'title': article.get('title', ''),
                    'published': article.get('published_utc', ''),
                    'url': article.get('article_url', ''),
                    'publisher': article.get('publisher', {}).get('name', ''),
                    'sentiment': self._analyze_sentiment(article.get('title', ''))
                })
            
            return processed_news
            
        except Exception as e:
            logger.error(f"Failed to process news sentiment: {e}")
            return {}
    
    def _analyze_sentiment(self, text: str) -> str:
        """Simple sentiment analysis based on keywords"""
        if not text:
            return "neutral"
        
        positive_words = ['up', 'rise', 'gain', 'profit', 'growth', 'positive', 'bullish', 'strong']
        negative_words = ['down', 'fall', 'loss', 'decline', 'negative', 'bearish', 'weak', 'drop']
        
        text_lower = text.lower()
        
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"
    
    def generate_summary_report(self, processed_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate a summary report for all processed data"""
        if not processed_data:
            return {}
        
        summary = {
            'total_tickers': len(processed_data),
            'analysis_date': datetime.now().isoformat(),
            'market_overview': self._generate_market_overview(processed_data),
            'top_performers': self._get_top_performers(processed_data),
            'volatility_analysis': self._analyze_volatility_distribution(processed_data)
        }
        
        return summary
    
    def _generate_market_overview(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate market overview statistics"""
        total_volume = sum(d.get('price_stats', {}).get('volume', 0) for d in data)
        avg_volatility = np.mean([d.get('volatility', {}).get('daily_volatility', 0) for d in data])
        
        return {
            'total_volume': total_volume,
            'average_volatility': avg_volatility,
            'tickers_analyzed': len(data)
        }
    
    def _get_top_performers(self, data: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """Get top performing tickers"""
        performers = []
        
        for ticker_data in data:
            price_change = ticker_data.get('price_change', {})
            if price_change:
                performers.append({
                    'ticker': ticker_data['ticker'],
                    'total_change_pct': price_change.get('total_change_pct', 0)
                })
        
        return sorted(performers, key=lambda x: x['total_change_pct'], reverse=True)[:top_n]
    
    def _analyze_volatility_distribution(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze volatility distribution across tickers"""
        volatilities = [d.get('volatility', {}).get('daily_volatility', 0) for d in data if d.get('volatility', {}).get('daily_volatility')]
        
        if not volatilities:
            return {}
        
        return {
            'min_volatility': min(volatilities),
            'max_volatility': max(volatilities),
            'avg_volatility': np.mean(volatilities),
            'median_volatility': np.median(volatilities)
        }
