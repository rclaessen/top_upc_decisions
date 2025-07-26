#!/usr/bin/env python3
"""
UPC Citation Tracker - GitHub Actions Version
Scrapes UPC decisions and generates citation analysis for GitHub Pages
"""

import sqlite3
import requests
import time
import re
import logging
import os
from datetime import datetime, date
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import PyPDF2
import io
from typing import List, Dict, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('upc_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class UPCDecisionScraper:
    def __init__(self, db_path: str = "upc_decisions.db", delay: float = 5.0):
        """
        Initialize the UPC Decision Scraper for GitHub Actions
        
        Args:
            db_path: Path to SQLite database file
            delay: Delay between requests in seconds (shorter for CI)
        """
        self.db_path = db_path
        self.delay = delay
        self.base_url = "https://www.unified-patent-court.org"
        self.decisions_url = "https://www.unified-patent-court.org/en/decisions-and-orders"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create UPC_decisions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS UPC_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    number TEXT NOT NULL UNIQUE,
                    court TEXT NOT NULL,
                    type_of_action TEXT NOT NULL,
                    parties TEXT NOT NULL,
                    pdf_url TEXT,
                    node TEXT,
                    fulltext TEXT,
                    decision_reference TEXT,
                    number_citations INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create index for faster citation queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_decision_reference 
                ON UPC_decisions(decision_reference)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_number
                ON UPC_decisions(number)
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def get_decisions_page(self, page: int = 0) -> BeautifulSoup:
        """Fetch decisions page from UPC website"""
        params = {
            'registry_number': '',
            'judgemet_reference': '',
            'judgement_type': 'All',
            'party_name': '',
            'court_type': 'All',
            'division_1': '125',
            'division_2': '126', 
            'division_3': '139',
            'division_4': '223',
            'keywords': '',
            'headnotes': '',
            'proceedings_lang': 'All',
            'judgement_date_from[date]': '',
            'judgement_date_to[date]': '',
            'location_id': 'All',
            'page': str(page)
        }
        
        try:
            logger.info(f"Fetching page {page}")
            response = self.session.get(self.decisions_url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
            
        except Exception as e:
            logger.error(f"Failed to fetch page {page}: {e}")
            raise
    
    def parse_decision_row(self, row) -> Optional[Dict]:
        """Parse a table row containing decision information"""
        try:
            cells = row.find_all('td')
            if len(cells) < 5:  # Angepasst für tatsächliche Tabellenstruktur
                return None
            
            # Extrahiere Daten aus Tabellenzellen (angepasst an echte UPC-Website)
            date_text = cells[0].get_text(strip=True)
            
            # Registry/Order Number (kann in verschiedenen Zellen sein)
            number = ""
            for i in range(1, min(3, len(cells))):
                cell_text = cells[i].get_text(strip=True)
                if cell_text and not cell_text.lower() in ['n/a', '-', '']:
                    number = cell_text
                    break
            
            if not number:
                return None
            
            # Weitere Felder extrahieren
            court = cells[2].get_text(strip=True) if len(cells) > 2 else "Unknown"
            type_of_action = cells[3].get_text(strip=True) if len(cells) > 3 else "Unknown"
            parties = cells[4].get_text(strip=True) if len(cells) > 4 else "Unknown"
            
            # PDF URL und Node aus Links extrahieren
            pdf_url = None
            node = None
            
            # Suche nach PDF-Links in allen Zellen
            for cell in cells:
                links = cell.find_all('a', href=True)
                for link in links:
                    href = link.get('href')
                    if href:
                        # PDF Link
                        if href.lower().endswith('.pdf'):
                            if not pdf_url or 'en' in href.lower():
                                pdf_url = urljoin(self.base_url, href)
                        
                        # Node Link (Full Details)
                        node_match = re.search(r'/node/(\d+)', href)
                        if node_match:
                            node = node_match.group(1)
            
            return {
                'date': date_text,
                'number': number,
                'court': court,
                'type_of_action': type_of_action,
                'parties': parties,
                'pdf_url': pdf_url,
                'node': node
            }
            
        except Exception as e:
            logger.warning(f"Failed to parse decision row: {e}")
            return None
    
    def extract_pdf_text(self, pdf_url: str) -> Tuple[str, str]:
        """Extract text from PDF and find decision reference"""
        try:
            logger.info(f"Extracting PDF: {pdf_url}")
            response = self.session.get(pdf_url, timeout=60)
            response.raise_for_status()
            
            # Extract text using PyPDF2
            pdf_file = io.BytesIO(response.content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            fulltext = ""
            for page in pdf_reader.pages:
                try:
                    fulltext += page.extract_text() + "\n"
                except Exception as e:
                    logger.warning(f"Failed to extract text from PDF page: {e}")
                    continue
            
            # Extract decision reference using regex
            decision_reference = ""
            decision_ref_patterns = [
                r'UPC_CFI_\d+/20\d{2}',
                r'UPC_CoA_\d+/20\d{2}',
                r'CFI_\d+/20\d{2}',
                r'CoA_\d+/20\d{2}'
            ]
            
            for pattern in decision_ref_patterns:
                matches = re.findall(pattern, fulltext)
                if matches:
                    decision_reference = matches[0]
                    if not decision_reference.startswith('UPC_'):
                        decision_reference = 'UPC_' + decision_reference
                    break
            
            return fulltext, decision_reference
            
        except Exception as e:
            logger.error(f"Failed to extract PDF text from {pdf_url}: {e}")
            return "", ""
    
    def decision_exists(self, number: str) -> bool:
        """Check if decision already exists in database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM UPC_decisions WHERE number = ?", (number,))
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            logger.error(f"Failed to check if decision exists: {e}")
            return False
    
    def save_decision(self, decision_data: Dict):
        """Save decision to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO UPC_decisions 
                (date, number, court, type_of_action, parties, pdf_url, node, fulltext, decision_reference, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                decision_data['date'],
                decision_data['number'],
                decision_data['court'],
                decision_data['type_of_action'],
                decision_data['parties'],
                decision_data['pdf_url'],
                decision_data['node'],
                decision_data.get('fulltext', ''),
                decision_data.get('decision_reference', '')
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"Saved decision: {decision_data['number']}")
            
        except Exception as e:
            logger.error(f"Failed to save decision: {e}")
    
    def scrape_decisions(self, max_pages: int = 10):
        """Main scraping function - limited pages for CI environment"""
        logger.info("Starting UPC decision scraping")
        new_decisions_count = 0
        
        for page in range(max_pages):
            try:
                soup = self.get_decisions_page(page)
                
                # Finde die Entscheidungstabelle
                table = soup.find('table', {'class': 'views-table'}) or soup.find('table')
                if not table:
                    logger.warning(f"No table found on page {page}")
                    break
                
                tbody = table.find('tbody')
                rows = tbody.find_all('tr') if tbody else table.find_all('tr')[1:]
                
                if not rows:
                    logger.info(f"No decisions found on page {page}")
                    break
                
                page_new_decisions = 0
                
                for row in rows:
                    decision_data = self.parse_decision_row(row)
                    if not decision_data or not decision_data['number']:
                        continue
                    
                    # Prüfe ob Entscheidung bereits existiert
                    if self.decision_exists(decision_data['number']):
                        logger.info(f"Decision {decision_data['number']} already exists")
                        continue
                    
                    # Extrahiere PDF-Text falls URL verfügbar
                    if decision_data['pdf_url']:
                        try:
                            fulltext, decision_reference = self.extract_pdf_text(decision_data['pdf_url'])
                            decision_data['fulltext'] = fulltext
                            decision_data['decision_reference'] = decision_reference
                        except Exception as e:
                            logger.warning(f"Failed to extract PDF for {decision_data['number']}: {e}")
                        
                        time.sleep(self.delay)  # Pause zwischen PDF-Downloads
                    
                    self.save_decision(decision_data)
                    new_decisions_count += 1
                    page_new_decisions += 1
                
                logger.info(f"Page {page}: Found {page_new_decisions} new decisions")
                
                # Wenn keine neuen Entscheidungen auf dieser Seite, stoppe
                if page_new_decisions == 0:
                    break
                    
                time.sleep(self.delay)  # Pause zwischen Seiten
                
            except Exception as e:
                logger.error(f"Error scraping page {page}: {e}")
                break
        
        logger.info(f"Finished scraping: {new_decisions_count} new decisions found")
    
    def calculate_citations(self):
        """Calculate citation counts for all decisions"""
        logger.info("Calculating citation counts")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, decision_reference FROM UPC_decisions WHERE decision_reference != '' AND decision_reference IS NOT NULL")
            decisions = cursor.fetchall()
            
            for decision_id, decision_ref in decisions:
                if not decision_ref:
                    continue
                
                # Zähle Zitierungen in anderen Entscheidungen
                cursor.execute("""
                    SELECT COUNT(*) FROM UPC_decisions 
                    WHERE id != ? AND fulltext LIKE ? AND fulltext IS NOT NULL
                """, (decision_id, f"%{decision_ref}%"))
                
                citation_count = cursor.fetchone()[0]
                
                cursor.execute("""
                    UPDATE UPC_decisions 
                    SET number_citations = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (citation_count, decision_id))
                
                if citation_count > 0:
                    logger.info(f"Decision {decision_ref}: {citation_count} citations")
            
            conn.commit()
            conn.close()
            logger.info("Finished calculating citations")
            
        except Exception as e:
            logger.error(f"Failed to calculate citations: {e}")
    
    def generate_html_report(self, output_file: str = "upc_top_100.html"):
        """Generate HTML report with top 100 cited decisions"""
        logger.info("Generating HTML report")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT decision_reference, number_citations, parties, court, type_of_action, node, date
                FROM UPC_decisions 
                WHERE decision_reference != '' AND decision_reference IS NOT NULL
                ORDER BY number_citations DESC, date DESC
                LIMIT 100
            """)
            
            decisions = cursor.fetchall()
            
            # Hole auch Gesamtstatistiken
            cursor.execute("SELECT COUNT(*) FROM UPC_decisions")
            total_decisions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM UPC_decisions WHERE decision_reference != ''")
            decisions_with_ref = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM UPC_decisions WHERE number_citations > 0")
            cited_decisions = cursor.fetchone()[0]
            
            conn.close()
            
            # Generiere HTML
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UPC Citation Tracker - Top 100</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
            margin-bottom: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 3em;
            font-weight: 700;
            letter-spacing: -1px;
        }}
        .header p {{
            margin: 15px 0 0 0;
            opacity: 0.9;
            font-size: 1.2em;
        }}
        .stats {{
            display: flex;
            justify-content: space-around;
            padding: 30px;
            background: #f8f9fa;
            text-align: center;
        }}
        .stat {{
            flex: 1;
        }}
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
            display: block;
        }}
        .stat-label {{
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .updated {{
            text-align: center;
            padding: 20px;
            background: #e3f2fd;
            color: #1565c0;
            font-weight: 500;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            background: #f8f9fa;
            padding: 20px 15px;
            text-align: left;
            font-weight: 600;
            color: #333;
            border-bottom: 2px solid #e9ecef;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        td {{
            padding: 15px;
            border-bottom: 1px solid #e9ecef;
            vertical-align: top;
        }}
        tr:hover {{
            background: #f8f9fa;
            transform: scale(1.001);
            transition: all 0.2s ease;
        }}
        .rank {{
            font-weight: bold;
            color: #667eea;
            text-align: center;
            width: 60px;
            font-size: 1.1em;
        }}
        .decision-ref {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
            font-family: 'Monaco', 'Menlo', monospace;
            padding: 8px 12px;
            background: #f0f4ff;
            border-radius: 6px;
            display: inline-block;
            transition: all 0.2s ease;
        }}
        .decision-ref:hover {{
            background: #667eea;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        .citations {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 8px 12px;
            border-radius: 20px;
            display: inline-block;
            font-size: 0.9em;
            font-weight: bold;
            text-align: center;
            min-width: 30px;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
        }}
        .parties {{
            max-width: 300px;
            line-height: 1.4;
            color: #333;
        }}
        .court, .action-type {{
            color: #666;
            font-size: 0.9em;
            line-height: 1.4;
        }}
        .court {{
            font-weight: 500;
        }}
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            .header h1 {{ font-size: 2em; }}
            .stats {{ flex-direction: column; gap: 20px; }}
            table {{ font-size: 0.9em; }}
            th, td {{ padding: 10px 8px; }}
            .parties {{ max-width: 200px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <h1>🏛️ UPC Citation Tracker</h1>
                <p>Top 100 Most Cited Decisions from the Unified Patent Court</p>
            </div>
            
            <div class="stats">
                <div class="stat">
                    <span class="stat-number">{total_decisions}</span>
                    <span class="stat-label">Total Decisions</span>
                </div>
                <div class="stat">
                    <span class="stat-number">{decisions_with_ref}</span>
                    <span class="stat-label">With References</span>
                </div>
                <div class="stat">
                    <span class="stat-number">{cited_decisions}</span>
                    <span class="stat-label">Cited Decisions</span>
                </div>
            </div>
            
            <div class="updated">
                🕒 Last Updated: {datetime.now().strftime('%d %B %Y at %H:%M UTC')}
            </div>
            
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Rank</th>
                            <th>Decision Reference</th>
                            <th>Citations</th>
                            <th>Parties</th>
                            <th>Court</th>
                            <th>Type of Action</th>
                        </tr>
                    </thead>
                    <tbody>"""
            
            for i, (decision_ref, citations, parties, court, action_type, node, date) in enumerate(decisions, 1):
                details_url = f"https://www.unified-patent-court.org/en/node/{node}" if node else "#"
                
                html_content += f"""
                        <tr>
                            <td class="rank">#{i}</td>
                            <td><a href="{details_url}" class="decision-ref" target="_blank" rel="noopener">{decision_ref or 'N/A'}</a></td>
                            <td><span class="citations">{citations}</span></td>
                            <td class="parties" title="{parties}">{parties}</td>
                            <td class="court">{court}</td>
                            <td class="action-type">{action_type}</td>
                        </tr>"""
            
            html_content += """
                    </tbody>
                </table>
            </div>
        </div>
        
        <div style="text-align: center; padding: 20px; color: rgba(255,255,255,0.8);">
            <p>📊 Data automatically scraped from <a href="https://www.unified-patent-court.org" style="color: rgba(255,255,255,0.9);">unified-patent-court.org</a></p>
            <p>🔄 Updates daily via GitHub Actions • 🚀 Powered by Python & SQLite</p>
        </div>
    </div>
</body>
</html>"""
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"HTML report generated: {output_file}")
            
        except Exception as e:
            logger.error(f"Failed to generate HTML report: {e}")
            raise
    
    def run_daily_update(self):
        """Main function for GitHub Actions"""
        logger.info("=== Starting UPC GitHub Actions Update ===")
        
        try:
            # Scrape mit Limit für CI-Umgebung
            self.scrape_decisions(max_pages=5)
            
            # Berechne Zitierungen
            self.calculate_citations()
            
            # Generiere HTML-Report
            self.generate_html_report()
            
            logger.info("=== GitHub Actions update completed successfully ===")
            
        except Exception as e:
            logger.error(f"GitHub Actions update failed: {e}")
            raise


def main():
    """Main function for GitHub Actions"""
    try:
        scraper = UPCDecisionScraper(delay=3.0)  # Kürzere Delays für CI
        scraper.run_daily_update()
        print("✅ UPC scraping completed successfully!")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
