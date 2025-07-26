#!/usr/bin/env python3
"""
Generate additional statistics for UPC Citation Tracker
"""

import sqlite3
import json
from datetime import datetime
from collections import Counter
import re

def generate_statistics(db_path="upc_decisions.db"):
    """Generate comprehensive statistics from the database"""
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Basic statistics
        cursor.execute("SELECT COUNT(*) FROM UPC_decisions")
        total_decisions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM UPC_decisions WHERE decision_reference != ''")
        decisions_with_ref = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM UPC_decisions WHERE number_citations > 0")
        cited_decisions = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(number_citations) FROM UPC_decisions")
        total_citations = cursor.fetchone()[0] or 0
        
        # Court statistics
        cursor.execute("SELECT court, COUNT(*) FROM UPC_decisions GROUP BY court ORDER BY COUNT(*) DESC")
        court_stats = cursor.fetchall()
        
        # Action type statistics
        cursor.execute("SELECT type_of_action, COUNT(*) FROM UPC_decisions GROUP BY type_of_action ORDER BY COUNT(*) DESC")
        action_stats = cursor.fetchall()
        
        # Monthly statistics
        cursor.execute("""
            SELECT substr(date, 1, 7) as month, COUNT(*) 
            FROM UPC_decisions 
            WHERE date != '' 
            GROUP BY substr(date, 1, 7) 
            ORDER BY month DESC 
            LIMIT 12
        """)
        monthly_stats = cursor.fetchall()
        
        # Top cited decisions
        cursor.execute("""
            SELECT decision_reference, number_citations, parties, court
            FROM UPC_decisions 
            WHERE number_citations > 0 
            ORDER BY number_citations DESC 
            LIMIT 20
        """)
        top_cited = cursor.fetchall()
        
        # Most active parties (simplified)
        cursor.execute("SELECT parties FROM UPC_decisions WHERE parties != ''")
        all_parties = cursor.fetchall()
        
        # Extract company names (simplified approach)
        party_counts = Counter()
        for (parties,) in all_parties:
            # Split by "v." and clean up
            if " v. " in parties:
                parts = parties.split(" v. ")
                for part in parts:
                    clean_part = part.strip()
                    if len(clean_part) > 5:  # Filter out very short names
                        party_counts[clean_part] += 1
        
        most_active_parties = party_counts.most_common(10)
        
        conn.close()
        
        # Generate HTML statistics page
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UPC Citation Tracker - Statistics</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
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
        }}
        .section {{
            padding: 30px;
        }}
        .section h2 {{
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #f8f9fa, #e9ecef);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            border-left: 5px solid #667eea;
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
        .chart-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
            margin: 30px 0;
        }}
        .chart {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
        }}
        .chart h3 {{
            margin-top: 0;
            color: #333;
        }}
        .bar {{
            display: flex;
            align-items: center;
            margin-bottom: 10px;
        }}
        .bar-label {{
            min-width: 200px;
            font-size: 0.9em;
            color: #666;
        }}
        .bar-fill {{
            background: linear-gradient(90deg, #667eea, #764ba2);
            height: 20px;
            border-radius: 10px;
            margin: 0 10px;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 8px;
            color: white;
            font-size: 0.8em;
            font-weight: bold;
        }}
        .top-cited {{
            overflow-x: auto;
        }}
        .top-cited table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .top-cited th, .top-cited td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e9ecef;
        }}
        .top-cited th {{
            background: #f8f9fa;
            font-weight: 600;
        }}
        .citation-badge {{
            background: #667eea;
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: bold;
        }}
        .updated {{
            text-align: center;
            padding: 20px;
            background: #e3f2fd;
            color: #1565c0;
            font-weight: 500;
        }}
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            .header h1 {{ font-size: 2em; }}
            .stats-grid {{ grid-template-columns: 1fr; }}
            .chart-container {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <h1>📊 UPC Statistics</h1>
                <p>Comprehensive analysis of Unified Patent Court decisions</p>
            </div>
            
            <div class="updated">
                🕒 Generated: {datetime.now().strftime('%d %B %Y at %H:%M UTC')}
            </div>
            
            <div class="section">
                <h2>📈 Overview</h2>
                <div class="stats-grid">
                    <div class="stat-card">
                        <span class="stat-number">{total_decisions}</span>
                        <span class="stat-label">Total Decisions</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{decisions_with_ref}</span>
                        <span class="stat-label">With References</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{cited_decisions}</span>
                        <span class="stat-label">Cited Decisions</span>
                    </div>
                    <div class="stat-card">
                        <span class="stat-number">{total_citations}</span>
                        <span class="stat-label">Total Citations</span>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <div class="chart-container">
                    <div class="chart">
                        <h3>🏛️ Decisions by Court</h3>"""
        
        # Court statistics chart
        if court_stats:
            max_court_count = max(count for _, count in court_stats)
            for court, count in court_stats[:8]:  # Top 8 courts
                percentage = (count / max_court_count) * 100
                html_content += f"""
                        <div class="bar">
                            <div class="bar-label">{court[:30]}{'...' if len(court) > 30 else ''}</div>
                            <div class="bar-fill" style="width: {percentage}%;">{count}</div>
                        </div>"""
        
        html_content += """
                    </div>
                    
                    <div class="chart">
                        <h3>⚖️ Action Types</h3>"""
        
        # Action type statistics chart
        if action_stats:
            max_action_count = max(count for _, count in action_stats)
            for action_type, count in action_stats[:8]:  # Top 8 action types
                percentage = (count / max_action_count) * 100
                html_content += f"""
                        <div class="bar">
                            <div class="bar-label">{action_type[:25]}{'...' if len(action_type) > 25 else ''}</div>
                            <div class="bar-fill" style="width: {percentage}%;">{count}</div>
                        </div>"""
        
        html_content += """
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>🎯 Top 20 Most Cited Decisions</h2>
                <div class="top-cited">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Decision Reference</th>
                                <th>Citations</th>
                                <th>Parties</th>
                                <th>Court</th>
                            </tr>
                        </thead>
                        <tbody>"""
        
        for i, (decision_ref, citations, parties, court) in enumerate(top_cited, 1):
            html_content += f"""
                            <tr>
                                <td>#{i}</td>
                                <td style="font-family: monospace; font-weight: bold;">{decision_ref}</td>
                                <td><span class="citation-badge">{citations}</span></td>
                                <td>{parties[:50]}{'...' if len(parties) > 50 else ''}</td>
                                <td>{court[:30]}{'...' if len(court) > 30 else ''}</td>
                            </tr>"""
        
        html_content += """
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="section">
                <div class="chart-container">
                    <div class="chart">
                        <h3>📅 Monthly Activity</h3>"""
        
        # Monthly statistics
        if monthly_stats:
            max_monthly = max(count for _, count in monthly_stats)
            for month, count in monthly_stats[:12]:
                percentage = (count / max_monthly) * 100
                html_content += f"""
                        <div class="bar">
                            <div class="bar-label">{month}</div>
                            <div class="bar-fill" style="width: {percentage}%;">{count}</div>
                        </div>"""
        
        html_content += """
                    </div>
                    
                    <div class="chart">
                        <h3>🏢 Most Active Parties</h3>"""
        
        # Most active parties
        if most_active_parties:
            max_party_count = max(count for _, count in most_active_parties)
            for party, count in most_active_parties[:10]:
                percentage = (count / max_party_count) * 100
                html_content += f"""
                        <div class="bar">
                            <div class="bar-label">{party[:25]}{'...' if len(party) > 25 else ''}</div>
                            <div class="bar-fill" style="width: {percentage}%;">{count}</div>
                        </div>"""
        
        html_content += """
                    </div>
                </div>
            </div>
        </div>
        
        <div style="text-align: center; padding: 20px; color: rgba(255,255,255,0.8);">
            <p>📊 Comprehensive UPC decision analysis • 🔄 Updated daily</p>
        </div>
    </div>
</body>
</html>"""
        
        # Write statistics HTML
        with open('upc_statistics.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print("✅ Statistics generated successfully!")
        
        # Also generate JSON data for potential API use
        stats_data = {
            'generated_at': datetime.now().isoformat(),
            'total_decisions': total_decisions,
            'decisions_with_ref': decisions_with_ref,
            'cited_decisions': cited_decisions,
            'total_citations': total_citations,
            'court_stats': dict(court_stats),
            'action_stats': dict(action_stats),
            'monthly_stats': dict(monthly_stats),
            'top_cited': [
                {
                    'decision_ref': ref,
                    'citations': cit,
                    'parties': parties,
                    'court': court
                } for ref, cit, parties, court in top_cited
            ],
            'most_active_parties': dict(most_active_parties)
        }
        
        with open('upc_stats.json', 'w', encoding='utf-8') as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)
        
        return stats_data
        
    except Exception as e:
        print(f"❌ Error generating statistics: {e}")
        raise

def main():
    """Main function"""
    try:
        generate_statistics()
        return 0
    except Exception as e:
        print(f"Statistics generation failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
