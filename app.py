import os
import re
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify, Response, abort
import csv
import io

app = Flask(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "dbname=allotment_research user=cwm6W"
)

ALLOTMENT_MAP_URL = os.environ.get("ALLOTMENT_MAP_URL", "http://localhost:8000")

@app.context_processor
def inject_map_url():
    return dict(allotment_map_url=ALLOTMENT_MAP_URL)


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding('UTF8')
    return conn


def slugify(name):
    """Convert tribe name to URL slug."""
    s = name.lower().strip()
    s = re.sub(r"[''']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def unslugify_tribe(slug):
    """Look up the original tribe name from a slug."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT tribe_identified FROM federal_register_claims ORDER BY tribe_identified")
        for (name,) in cur.fetchall():
            if slugify(name) == slug:
                return name
        return None
    finally:
        conn.close()


DOC_CLASS_CODES = {
    "Serial Land Patent": "SER",
    "Miscellaneous Volume Patent": "MV",
    "Indian Fee Patent": "IF",
    "State Land Patent": "STA",
    "Indian Allotment Patent": "IA",
}


def glo_url(accession, doc_class):
    """Build a GLO record URL from accession number and document class."""
    if not accession:
        return None
    code = DOC_CLASS_CODES.get(doc_class, "SER")
    return f"https://glorecords.blm.gov/details/patent/default.aspx?accession={accession}&docClass={code}"


def linkify_remarks(text):
    """Turn patent number references in remarks into GLO links."""
    if not text:
        return text
    def make_link(accession):
        url = f"https://glorecords.blm.gov/details/patent/default.aspx?accession={accession}&docClass=SER"
        return f'<a href="{url}" target="_blank">{accession}</a>'
    # Match "NR XXXXXX" and also "AND XXXXXX" patterns
    text = re.sub(r'(?:NR\.?|AND)\s+(\d{4,})', lambda m: m.group(0).replace(m.group(1), make_link(m.group(1))), text)
    return text


def add_claim_type_filter(claim_type, conditions, params):
    """Add claim type filter, grouping variants together."""
    if claim_type:
        if claim_type == "ALL FORCED FEE":
            conditions.append("fr.claim_type ILIKE %s")
            params.append("%FORCED FEE%")
        else:
            conditions.append("fr.claim_type ILIKE %s")
            params.append(f"%{claim_type}%")


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def index():
    """Main search / browse page."""
    conn = get_db()
    try:
        cur = conn.cursor()
        # Get tribe list with counts for the dropdown
        cur.execute("""
            SELECT tribe_identified, COUNT(*) as cnt
            FROM federal_register_claims
            GROUP BY tribe_identified
            ORDER BY tribe_identified
        """)
        tribes = cur.fetchall()

        # Grouped claim type categories
        claim_types = [
            ("ALL FORCED FEE", "Forced Fee Patent (all variants)"),
            ("SECRETARIAL TRANSFER", "Secretarial Transfer (all variants)"),
            ("HEIRSHIP FORCED FEE", "Heirship Forced Fee"),
            ("WELFARE FORCED FEE", "Welfare Forced Fee"),
            ("RECOVER TITLE", "Recover Title"),
        ]

        return render_template("index.html", tribes=tribes, claim_types=claim_types, slugify=slugify)
    finally:
        conn.close()


@app.route("/api/search")
def api_search():
    """JSON API for search results (used by DataTables)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # DataTables parameters
        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)
        search_value = request.args.get("search[value]", "").strip()

        # Custom filters
        tribe = request.args.get("tribe", "").strip()
        claim_type = request.args.get("claim_type", "").strip()
        name_search = request.args.get("name", "").strip()
        allotment_search = request.args.get("allotment", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        # Order
        order_col_idx = request.args.get("order[0][column]", 0, type=int)
        order_dir = request.args.get("order[0][dir]", "asc")
        order_cols = ["fr.case_number", "fr.allottee_name", "fr.tribe_identified",
                      "fr.allotment_number", "fr.claim_type", "min_date"]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        conditions = []
        params = []

        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)
        add_claim_type_filter(claim_type, conditions, params)
        if name_search:
            conditions.append("fr.allottee_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment_search:
            conditions.append("fr.allotment_number = %s")
            params.append(allotment_search)
        if search_value:
            conditions.append("""(
                fr.allottee_name ILIKE %s OR
                fr.case_number ILIKE %s OR
                fr.allotment_number ILIKE %s OR
                fr.tribe_identified ILIKE %s
            )""")
            sv = f"%{search_value}%"
            params.extend([sv, sv, sv, sv])
        if date_from:
            conditions.append("ffp.patents_signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("ffp.patents_signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Total records (unfiltered)
        cur.execute("SELECT COUNT(*) as cnt FROM federal_register_claims")
        total = cur.fetchone()["cnt"]

        # Filtered count
        count_sql = f"""
            SELECT COUNT(DISTINCT fr.id)
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
        """
        cur.execute(count_sql, params)
        filtered = cur.fetchone()["count"]

        # Main query
        data_sql = f"""
            SELECT
                fr.id,
                fr.case_number,
                fr.allottee_name,
                fr.tribe_identified,
                fr.allotment_number,
                fr.claim_type,
                MIN(ffp.patents_signature_date) as min_date,
                COUNT(ffp.id) as patent_count
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY fr.id, fr.case_number, fr.allottee_name, fr.tribe_identified,
                     fr.allotment_number, fr.claim_type
            ORDER BY {order_col} {order_dir}
            LIMIT %s OFFSET %s
        """
        cur.execute(data_sql, params + [length, start])
        rows = cur.fetchall()

        # Format for DataTables
        data = []
        for r in rows:
            sig_date = ""
            if r["min_date"]:
                sig_date = r["min_date"].strftime("%Y-%m-%d") if hasattr(r["min_date"], "strftime") else str(r["min_date"])
            data.append({
                "id": r["id"],
                "case_number": r["case_number"],
                "allottee_name": r["allottee_name"],
                "tribe": r["tribe_identified"],
                "tribe_slug": slugify(r["tribe_identified"]),
                "allotment_number": r["allotment_number"],
                "claim_type": r["claim_type"],
                "patent_date": sig_date,
                "patent_count": r["patent_count"],
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/search/csv")
def api_search_csv():
    """CSV download of current search results."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        tribe = request.args.get("tribe", "").strip()
        claim_type = request.args.get("claim_type", "").strip()
        name_search = request.args.get("name", "").strip()
        allotment_search = request.args.get("allotment", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        conditions = []
        params = []

        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)
        add_claim_type_filter(claim_type, conditions, params)
        if name_search:
            conditions.append("fr.allottee_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment_search:
            conditions.append("fr.allotment_number = %s")
            params.append(allotment_search)
        if date_from:
            conditions.append("ffp.patents_signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("ffp.patents_signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        sql = f"""
            SELECT
                fr.case_number,
                fr.allottee_name,
                fr.tribe_identified,
                fr.allotment_number,
                fr.claim_type,
                fr.document_source,
                ffp.glo_patentees,
                ffp.patents_accession_number,
                ffp.patents_signature_date,
                ffp.patents_document_class,
                ffp.patent_state
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            ORDER BY fr.tribe_identified, fr.case_number
        """
        cur.execute(sql, params)
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Case Number", "Allottee Name", "Tribe", "Allotment Number",
            "Claim Type", "Document Source", "GLO Patentee(s)",
            "Accession Number", "Patent Date", "Document Class", "State"
        ])
        for r in rows:
            writer.writerow([
                r["case_number"], r["allottee_name"], r["tribe_identified"],
                r["allotment_number"], r["claim_type"], r["document_source"],
                r["glo_patentees"], r["patents_accession_number"],
                r["patents_signature_date"], r["patents_document_class"],
                r["patent_state"],
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=federal_register_claims.csv"}
        )
    finally:
        conn.close()


@app.route("/claim/<int:claim_id>")
def claim_detail(claim_id):
    """Individual claim page."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get the claim
        cur.execute("""
            SELECT * FROM federal_register_claims WHERE id = %s
        """, (claim_id,))
        claim = cur.fetchone()
        if not claim:
            abort(404)

        # Get linked patents
        cur.execute("""
            SELECT
                ffp.*,
                fp.glo_url as fee_glo_url,
                fp.acres as fee_acres
            FROM forced_fee_patents_rails ffp
            LEFT JOIN fee_patents fp ON fp.accession_number = ffp.patents_accession_number
            WHERE LTRIM(ffp.case_number, '0') = LTRIM(%s, '0')
              AND ffp.fedreg_allottee = %s
            ORDER BY ffp.patents_signature_date
        """, (claim["case_number"], claim["allottee_name"]))
        patents = cur.fetchall()

        # Get parcels for linked patents (via allotment number + tribe)
        parcels = []
        if patents:
            # Use the first patent's tribe info to find parcels
            for p in patents:
                if p.get("patents_glo_tribe"):
                    cur.execute("""
                        SELECT DISTINCT
                            state, county, meridian,
                            township_number, township_direction,
                            range_number, range_direction,
                            section_number, aliquot_parts
                        FROM parcels_patents_by_tribe
                        WHERE glo_tribe_id = %s
                          AND indian_allotment_number = %s
                    """, (p["patents_glo_tribe"], p.get("fedreg_allotment", "")))
                    parcels.extend(cur.fetchall())

        # If no patent linkages found (e.g. secretarial transfers),
        # search fee_patents and trust_patents by allotment number + tribe
        allotment_patents = []
        if not patents and claim.get("allotment_number"):
            tribe = claim["tribe_identified"]
            allotment = claim["allotment_number"]
            cur.execute("""
                SELECT accession_number, signature_date, document_class,
                       indian_allotment_number, tribe_normalized, state,
                       acres, remarks, glo_url, 'fee' as patent_type
                FROM fee_patents
                WHERE indian_allotment_number = %s
                  AND tribe_normalized = %s
                UNION ALL
                SELECT accession_number, signature_date, document_class,
                       indian_allotment_number, tribe_normalized, state,
                       acres, remarks, glo_url, 'trust' as patent_type
                FROM trust_patents
                WHERE indian_allotment_number = %s
                  AND tribe_normalized = %s
                ORDER BY signature_date
            """, (allotment, tribe, allotment, tribe))
            allotment_patents = cur.fetchall()

        # Get trust-to-fee linkages if we have fee accession numbers
        trust_links = []
        for p in patents:
            if p.get("patents_accession_number"):
                cur.execute("""
                    SELECT * FROM trust_fee_linkages
                    WHERE fee_accession = %s
                """, (p["patents_accession_number"],))
                trust_links.extend(cur.fetchall())

        # Look up BLM patent objectids for cross-linking
        blm_patent_ids = {}
        for p in patents:
            acc = p.get("patents_accession_number")
            if acc:
                cur.execute("""
                    SELECT objectid FROM blm_allotment_patents
                    WHERE accession_number = %s LIMIT 1
                """, (acc,))
                row = cur.fetchone()
                if row:
                    blm_patent_ids[acc] = row["objectid"]

        return render_template(
            "claim.html",
            claim=claim,
            patents=patents,
            allotment_patents=allotment_patents,
            parcels=parcels,
            trust_links=trust_links,
            blm_patent_ids=blm_patent_ids,
            slugify=slugify,
            glo_url=glo_url,
            linkify_remarks=linkify_remarks,
        )
    finally:
        conn.close()


@app.route("/tribe/<tribe_slug>")
def tribe_detail(tribe_slug):
    """Tribe landing page."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        abort(404)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Summary stats
        cur.execute("""
            SELECT COUNT(*) as total_claims
            FROM federal_register_claims
            WHERE tribe_identified = %s
        """, (tribe_name,))
        stats = cur.fetchone()

        # Date range from linked patents
        cur.execute("""
            SELECT
                MIN(ffp.patents_signature_date) as earliest,
                MAX(ffp.patents_signature_date) as latest,
                COUNT(DISTINCT fr.id) as linked_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE fr.tribe_identified = %s
        """, (tribe_name,))
        date_info = cur.fetchone()

        # Timeline data: all fee patents by year + subset linked to FR claims
        cur.execute("""
            SELECT
                all_patents.yr,
                all_patents.total as total_patents,
                COALESCE(linked.linked_count, 0) as linked_to_claims
            FROM (
                SELECT EXTRACT(YEAR FROM signature_date::date)::int as yr,
                       COUNT(*) as total
                FROM fee_patents
                WHERE tribe_normalized = %s
                  AND signature_date IS NOT NULL AND signature_date != ''
                GROUP BY yr
            ) all_patents
            LEFT JOIN (
                SELECT
                    EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                    COUNT(DISTINCT fr.id) as linked_count
                FROM federal_register_claims fr
                JOIN forced_fee_patents_rails ffp
                    ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                    AND fr.allottee_name = ffp.fedreg_allottee
                WHERE fr.tribe_identified = %s
                  AND ffp.patents_signature_date IS NOT NULL
                GROUP BY yr
            ) linked ON all_patents.yr = linked.yr
            ORDER BY all_patents.yr
        """, (tribe_name, tribe_name))
        timeline_data = cur.fetchall()

        return render_template(
            "tribe.html",
            tribe_name=tribe_name,
            tribe_slug=tribe_slug,
            stats=stats,
            date_info=date_info,
            timeline_data=timeline_data,
            slugify=slugify,
        )
    finally:
        conn.close()


@app.route("/api/tribe/<tribe_slug>/claims")
def api_tribe_claims(tribe_slug):
    """JSON API for tribe claims table (DataTables)."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        return jsonify({"error": "Tribe not found"}), 404

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)
        search_value = request.args.get("search[value]", "").strip()

        order_col_idx = request.args.get("order[0][column]", 0, type=int)
        order_dir = request.args.get("order[0][dir]", "asc")
        order_cols = ["fr.case_number", "fr.allottee_name", "fr.allotment_number",
                      "min_date", "patent_count"]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        conditions = ["fr.tribe_identified = %s"]
        params = [tribe_name]

        if search_value:
            conditions.append("""(
                fr.allottee_name ILIKE %s OR
                fr.case_number ILIKE %s OR
                fr.allotment_number ILIKE %s
            )""")
            sv = f"%{search_value}%"
            params.extend([sv, sv, sv])

        where = "WHERE " + " AND ".join(conditions)

        # Count
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM federal_register_claims fr {where}
        """, params[:1] if not search_value else params)
        total = cur.fetchone()["cnt"]

        cur.execute(f"""
            SELECT COUNT(DISTINCT fr.id)
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
        """, params)
        filtered = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT
                fr.id,
                fr.case_number,
                fr.allottee_name,
                fr.allotment_number,
                MIN(ffp.patents_signature_date) as min_date,
                COUNT(ffp.id) as patent_count
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY fr.id, fr.case_number, fr.allottee_name, fr.allotment_number
            ORDER BY {order_col} {order_dir}
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        data = []
        for r in rows:
            sig_date = ""
            if r["min_date"]:
                sig_date = r["min_date"].strftime("%Y-%m-%d") if hasattr(r["min_date"], "strftime") else str(r["min_date"])
            data.append({
                "id": r["id"],
                "case_number": r["case_number"],
                "allottee_name": r["allottee_name"],
                "allotment_number": r["allotment_number"],
                "patent_date": sig_date,
                "patent_count": r["patent_count"],
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/tribe/<tribe_slug>/csv")
def tribe_csv(tribe_slug):
    """CSV download for a tribe."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        abort(404)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                fr.case_number, fr.allottee_name, fr.allotment_number,
                fr.claim_type, fr.document_source,
                ffp.glo_patentees, ffp.patents_accession_number,
                ffp.patents_signature_date, ffp.patents_document_class,
                ffp.patent_state
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE fr.tribe_identified = %s
            ORDER BY fr.case_number
        """, (tribe_name,))
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Case Number", "Allottee Name", "Allotment Number",
            "Claim Type", "Document Source", "GLO Patentee(s)",
            "Accession Number", "Patent Date", "Document Class", "State"
        ])
        for r in rows:
            writer.writerow([
                r["case_number"], r["allottee_name"], r["allotment_number"],
                r["claim_type"], r["document_source"], r["glo_patentees"],
                r["patents_accession_number"], r["patents_signature_date"],
                r["patents_document_class"], r["patent_state"],
            ])

        filename = f"{tribe_slug}_claims.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        conn.close()


@app.route("/tribes")
def tribes_list():
    """List all tribes with claims."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                fr.tribe_identified,
                COUNT(DISTINCT fr.id) as claim_count,
                COUNT(ffp.id) as patent_linkage_count,
                MIN(ffp.patents_signature_date) as earliest,
                MAX(ffp.patents_signature_date) as latest
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            GROUP BY fr.tribe_identified
            ORDER BY fr.tribe_identified
        """)
        tribes = cur.fetchall()
        return render_template("tribes.html", tribes=tribes, slugify=slugify)
    finally:
        conn.close()


@app.route("/timeline")
def timeline():
    """Timeline visualization page."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get tribes for filter
        cur.execute("""
            SELECT DISTINCT tribe_identified
            FROM federal_register_claims
            ORDER BY tribe_identified
        """)
        tribes = [r["tribe_identified"] for r in cur.fetchall()]

        # Overall timeline data
        cur.execute("""
            SELECT
                EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                COUNT(DISTINCT fr.id) as claim_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE ffp.patents_signature_date IS NOT NULL
            GROUP BY yr
            ORDER BY yr
        """)
        timeline_data = cur.fetchall()

        return render_template("timeline.html", tribes=tribes,
                               timeline_data=timeline_data, slugify=slugify)
    finally:
        conn.close()


@app.route("/api/timeline")
def api_timeline():
    """JSON API for timeline data, optionally filtered by tribe."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        conditions = ["ffp.patents_signature_date IS NOT NULL"]
        params = []
        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)

        where = "WHERE " + " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                COUNT(DISTINCT fr.id) as claim_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY yr
            ORDER BY yr
        """, params)
        data = cur.fetchall()

        return jsonify([{"year": r["yr"], "count": r["claim_count"]} for r in data])
    finally:
        conn.close()


@app.route("/patents")
def patents_index():
    """Browse / search all BLM allotment patents."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT preferred_name FROM blm_allotment_patents WHERE preferred_name IS NOT NULL ORDER BY preferred_name")
        tribes = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT state FROM blm_allotment_patents WHERE state IS NOT NULL ORDER BY state")
        states = [r[0] for r in cur.fetchall()]
        return render_template("patents.html", tribes=tribes, states=states)
    finally:
        conn.close()


FEE_AUTHORITIES = (
    'Indian Fee Patent', 'Indian Fee Patent (Heir)', 'Indian Fee Patent (IRA)',
    'Indian Fee Patent (Non-IRA)', 'Indian Fee Patent-Misc.',
    'Indian Fee Patent-Term or Non', 'Indian Homestead Fee Patent',
    'Indian Trust to Fee',
)

TRUST_AUTHORITIES = (
    'Indian Trust Patent', 'Indian Trust Patent (Wind R)',
    'Indian Homestead Trust', 'Indian Reissue Trust',
    'Indian Allotment - General', 'Indian Allotment in Nat. Forest',
    'Indian Allotment-Wyandotte', 'Indian Partition',
)


@app.route("/api/patents")
def api_patents():
    """JSON API for patent search (DataTables server-side)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)

        name_search = request.args.get("name", "").strip()
        allotment = request.args.get("allotment", "").strip()
        tribe = request.args.get("tribe", "").strip()
        state = request.args.get("state", "").strip()
        patent_type = request.args.get("patent_type", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        order_col_idx = request.args.get("order[0][column]", 0, type=int)
        order_dir = request.args.get("order[0][dir]", "asc")
        order_cols = ["full_name", "preferred_name", "state",
                      "indian_allotment_number", "authority", "signature_date", "forced_fee"]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        conditions = []
        params = []

        if name_search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment:
            conditions.append("indian_allotment_number = %s")
            params.append(allotment)
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)
        if state:
            conditions.append("state = %s")
            params.append(state)
        if patent_type == "fee":
            conditions.append("authority IN %s")
            params.append(FEE_AUTHORITIES)
        elif patent_type == "trust":
            conditions.append("authority IN %s")
            params.append(TRUST_AUTHORITIES)
        elif patent_type == "forced":
            conditions.append("forced_fee = 'True'")
        if date_from:
            conditions.append("signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute("SELECT COUNT(*) as cnt FROM blm_allotment_patents")
        total = cur.fetchone()["cnt"]

        cur.execute(f"SELECT COUNT(*) as cnt FROM blm_allotment_patents {where}", params)
        filtered = cur.fetchone()["cnt"]

        cur.execute(f"""
            SELECT objectid, full_name, preferred_name, state,
                   indian_allotment_number, authority, signature_date, forced_fee
            FROM blm_allotment_patents
            {where}
            ORDER BY {order_col} {order_dir} NULLS LAST
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        data = []
        for r in rows:
            sig_date = ""
            if r["signature_date"]:
                sig_date = r["signature_date"].strftime("%Y-%m-%d") if hasattr(r["signature_date"], "strftime") else str(r["signature_date"])
            data.append({
                "objectid": r["objectid"],
                "full_name": r["full_name"] or "",
                "preferred_name": r["preferred_name"] or "",
                "state": r["state"] or "",
                "allotment_number": r["indian_allotment_number"] or "",
                "authority": r["authority"] or "",
                "signature_date": sig_date,
                "forced_fee": r["forced_fee"] == "True",
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/patents/csv")
def api_patents_csv():
    """CSV download of patent search results."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        name_search = request.args.get("name", "").strip()
        allotment = request.args.get("allotment", "").strip()
        tribe = request.args.get("tribe", "").strip()
        state = request.args.get("state", "").strip()
        patent_type = request.args.get("patent_type", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        conditions = []
        params = []

        if name_search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment:
            conditions.append("indian_allotment_number = %s")
            params.append(allotment)
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)
        if state:
            conditions.append("state = %s")
            params.append(state)
        if patent_type == "fee":
            conditions.append("authority IN %s")
            params.append(FEE_AUTHORITIES)
        elif patent_type == "trust":
            conditions.append("authority IN %s")
            params.append(TRUST_AUTHORITIES)
        elif patent_type == "forced":
            conditions.append("forced_fee = 'True'")
        if date_from:
            conditions.append("signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute(f"""
            SELECT accession_number, full_name, preferred_name, state, county,
                   indian_allotment_number, authority, signature_date, forced_fee,
                   meridian, township_number, township_direction,
                   range_number, range_direction, section_number, aliquot_parts, remarks
            FROM blm_allotment_patents
            {where}
            ORDER BY preferred_name, full_name
        """, params)
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Accession Number", "Full Name", "Tribe", "State", "County",
            "Allotment Number", "Authority", "Signature Date", "Forced Fee",
            "Meridian", "Township", "Township Dir", "Range", "Range Dir",
            "Section", "Aliquot Parts", "Remarks"
        ])
        for r in rows:
            sig_date = ""
            if r["signature_date"]:
                sig_date = r["signature_date"].strftime("%Y-%m-%d") if hasattr(r["signature_date"], "strftime") else str(r["signature_date"])
            writer.writerow([
                r["accession_number"], r["full_name"], r["preferred_name"],
                r["state"], r["county"], r["indian_allotment_number"],
                r["authority"], sig_date, r["forced_fee"],
                r["meridian"], r["township_number"], r["township_direction"],
                r["range_number"], r["range_direction"], r["section_number"],
                r["aliquot_parts"], r["remarks"],
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=blm_allotment_patents.csv"}
        )
    finally:
        conn.close()


@app.route("/patent/<int:objectid>")
def patent_detail(objectid):
    """Individual BLM patent record page."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT * FROM blm_allotment_patents WHERE objectid = %s", (objectid,))
        patent = cur.fetchone()
        if not patent:
            abort(404)

        # Cross-link: check if this patent's accession_number is in forced_fee_patents_rails
        linked_claim = None
        if patent.get("accession_number"):
            cur.execute("""
                SELECT fr.id, fr.allottee_name, fr.case_number, fr.tribe_identified
                FROM forced_fee_patents_rails ffp
                JOIN federal_register_claims fr
                    ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                    AND fr.allottee_name = ffp.fedreg_allottee
                WHERE ffp.patents_accession_number = %s
                LIMIT 1
            """, (patent["accession_number"],))
            linked_claim = cur.fetchone()

        return render_template(
            "patent.html",
            patent=patent,
            linked_claim=linked_claim,
            glo_url=glo_url,
            slugify=slugify,
        )
    finally:
        conn.close()


@app.route("/patents/timeline")
def patents_timeline():
    """Timeline of all fee patents from BLM dataset."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT DISTINCT preferred_name FROM blm_allotment_patents WHERE preferred_name IS NOT NULL ORDER BY preferred_name")
        tribes = [r["preferred_name"] for r in cur.fetchall()]

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM signature_date)::int as yr,
                COUNT(*) FILTER (WHERE authority IN {FEE_AUTHORITIES!r}) as fee_count,
                COUNT(*) FILTER (WHERE authority IN {TRUST_AUTHORITIES!r}) as trust_count,
                COUNT(*) FILTER (WHERE authority NOT IN {FEE_AUTHORITIES!r} AND authority NOT IN {TRUST_AUTHORITIES!r}) as other_count,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_count
            FROM blm_allotment_patents
            WHERE signature_date IS NOT NULL
            GROUP BY yr
            ORDER BY yr
        """)
        timeline_data = cur.fetchall()

        # Murray trust removal data (1948-1957)
        cur.execute("""
            SELECT year, SUM(acres_removed) as acres
            FROM murray_trust_removal
            WHERE area_office != 'Grand Total'
            GROUP BY year ORDER BY year
        """)
        murray_data = [{"year": r["year"], "acres_removed": float(r["acres"])} for r in cur.fetchall()]

        return render_template("patents_timeline.html", tribes=tribes,
                               timeline_data=timeline_data, murray_data=murray_data)
    finally:
        conn.close()


@app.route("/api/patents/timeline")
def api_patents_timeline():
    """JSON API for patent timeline, optionally filtered by tribe."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        conditions = ["signature_date IS NOT NULL"]
        params = []
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)

        where = "WHERE " + " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM signature_date)::int as yr,
                COUNT(*) FILTER (WHERE authority IN {FEE_AUTHORITIES!r}) as fee_count,
                COUNT(*) FILTER (WHERE authority IN {TRUST_AUTHORITIES!r}) as trust_count,
                COUNT(*) FILTER (WHERE authority NOT IN {FEE_AUTHORITIES!r} AND authority NOT IN {TRUST_AUTHORITIES!r}) as other_count,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_count
            FROM blm_allotment_patents
            {where}
            GROUP BY yr
            ORDER BY yr
        """, params)
        data = cur.fetchall()

        timeline = [{"year": r["yr"], "fee": r["fee_count"], "trust": r["trust_count"],
                      "other": r["other_count"], "forced": r.get("forced_count", 0)} for r in data]

        # Murray trust removal data (1948-1957) — acres removed from trust by year
        cur.execute("""
            SELECT year, SUM(acres_removed) as acres
            FROM murray_trust_removal
            WHERE area_office != 'Grand Total'
            GROUP BY year ORDER BY year
        """)
        murray = [{"year": r["year"], "acres_removed": float(r["acres"])} for r in cur.fetchall()]

        return jsonify({"timeline": timeline, "murray": murray})
    finally:
        conn.close()


@app.route("/sankey")
def sankey():
    """Sankey flow diagram: trust -> fee -> forced pathways."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT preferred_name FROM blm_allotment_patents WHERE preferred_name IS NOT NULL ORDER BY preferred_name")
        tribes = [r[0] for r in cur.fetchall()]
        return render_template("sankey.html", tribes=tribes)
    finally:
        conn.close()


@app.route("/api/sankey")
def api_sankey():
    """JSON API returning node/link data for the Sankey diagram."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Build WHERE clause for BLM patents
        blm_where = ""
        blm_params = []
        if tribe:
            blm_where = "AND preferred_name = %s"
            blm_params = [tribe]

        # Patent categories by authority (ignore forced_fee BLM flag — use FR claims as ground truth)
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE authority IN %s) as trust_count,
                COUNT(*) FILTER (WHERE authority IN %s) as fee_count,
                COUNT(*) FILTER (WHERE authority NOT IN %s AND authority NOT IN %s) as other_count
            FROM blm_allotment_patents
            WHERE TRUE {blm_where}
        """, [TRUST_AUTHORITIES, FEE_AUTHORITIES, TRUST_AUTHORITIES, FEE_AUTHORITIES] + blm_params)
        counts = cur.fetchone()
        trust_count = counts["trust_count"]
        fee_count = counts["fee_count"]
        other_count = counts["other_count"]

        # Trust-to-fee linkages
        link_where = ""
        link_params = []
        if tribe:
            link_where = "WHERE tribe_normalized = %s"
            link_params = [tribe]

        # Trust patents that were later converted to fee
        cur.execute(f"""
            SELECT COUNT(DISTINCT trust_accession) as cnt FROM trust_fee_linkages {link_where}
        """, link_params)
        trust_converted = cur.fetchone()["cnt"]
        trust_remained = trust_count - trust_converted

        # Fee patents with a known trust origin
        cur.execute(f"""
            SELECT COUNT(DISTINCT fee_accession) as cnt FROM trust_fee_linkages {link_where}
        """, link_params)
        fee_with_trust_origin = cur.fetchone()["cnt"]
        fee_direct = fee_count - fee_with_trust_origin

        # Federal Register claims counts
        fr_where = ""
        fr_params = []
        if tribe:
            # Try matching tribe name between FR claims and BLM patents
            fr_where = "WHERE fr.tribe_identified = %s"
            fr_params = [tribe]

        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE fr.claim_type ILIKE '%%FORCED FEE%%') as forced_claims,
                COUNT(*) FILTER (WHERE fr.claim_type ILIKE '%%SECRETARIAL%%') as sec_claims
            FROM federal_register_claims fr
            {fr_where}
        """, fr_params)
        fr_row = cur.fetchone()
        fr_forced_claims = fr_row["forced_claims"]
        fr_sec_claims = fr_row["sec_claims"]

        # Linked FR claims (matched to BLM patents)
        cur.execute(f"""
            SELECT COUNT(DISTINCT fr.id) as cnt
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {fr_where}
        """, fr_params)
        fr_linked = cur.fetchone()["cnt"]
        fr_total = fr_forced_claims + fr_sec_claims
        fr_unlinked = fr_total - fr_linked

        # Conversion timing and acreage stats from trust_fee_linkages
        link_and = link_where.replace('WHERE', 'AND') if link_where else ''
        cur.execute(f"""
            SELECT
                COUNT(*) as cnt,
                AVG(years_to_conversion) as avg_years,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY years_to_conversion) as median_years,
                MIN(years_to_conversion) as min_years,
                MAX(years_to_conversion) as max_years,
                COUNT(*) FILTER (WHERE years_to_conversion < 10) as fast_conversions,
                COUNT(*) FILTER (WHERE years_to_conversion >= 10 AND years_to_conversion < 25) as medium_conversions,
                COUNT(*) FILTER (WHERE years_to_conversion >= 25) as slow_conversions
            FROM trust_fee_linkages
            WHERE years_to_conversion IS NOT NULL
                AND years_to_conversion >= 0
                AND years_to_conversion < 200
                {link_and}
        """, link_params)
        timing = cur.fetchone()

        # Acreage totals
        cur.execute(f"""
            SELECT
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres,
                ROUND(AVG(trust_acres)::numeric, 1) as avg_trust_acres,
                ROUND(AVG(fee_acres)::numeric, 1) as avg_fee_acres,
                COUNT(*) FILTER (WHERE fee_acres < trust_acres) as shrunk,
                COUNT(*) FILTER (WHERE fee_acres = trust_acres) as same,
                COUNT(*) FILTER (WHERE fee_acres > trust_acres) as grew
            FROM trust_fee_linkages
            {link_where}
        """, link_params)
        acreage = cur.fetchone()

        # Acreage by conversion speed
        cur.execute(f"""
            SELECT
                CASE
                    WHEN years_to_conversion < 10 THEN 'fast'
                    WHEN years_to_conversion < 25 THEN 'medium'
                    ELSE 'slow'
                END as speed,
                COUNT(*) as cnt,
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres
            FROM trust_fee_linkages
            WHERE years_to_conversion IS NOT NULL
                AND years_to_conversion >= 0
                AND years_to_conversion < 200
                {link_and}
            GROUP BY 1
        """, link_params)
        acreage_by_speed = {}
        for row in cur.fetchall():
            acreage_by_speed[row["speed"]] = {
                "count": row["cnt"],
                "trust_acres": int(row["trust_acres"]) if row["trust_acres"] else 0,
                "fee_acres": int(row["fee_acres"]) if row["fee_acres"] else 0,
            }

        # Top tribes by fee acreage (land that left trust protection)
        cur.execute(f"""
            SELECT tribe_normalized,
                COUNT(*) as cnt,
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres
            FROM trust_fee_linkages
            WHERE tribe_normalized IS NOT NULL AND tribe_normalized != ''
                {link_and}
            GROUP BY tribe_normalized
            ORDER BY SUM(fee_acres) DESC
            LIMIT 10
        """, link_params)
        top_tribes_acreage = []
        for row in cur.fetchall():
            top_tribes_acreage.append({
                "tribe": row["tribe_normalized"],
                "conversions": row["cnt"],
                "trust_acres": int(row["trust_acres"]) if row["trust_acres"] else 0,
                "fee_acres": int(row["fee_acres"]) if row["fee_acres"] else 0,
            })

        # Wilson Report 1934 baseline (if tribe selected)
        wilson_data = None
        if tribe:
            cur.execute("""
                SELECT reservation_name, original_area_acres, allotment_acreage,
                    land_alienated_acres, total_allotments_made,
                    living_total_acres, deceased_total_acres,
                    tribal_total_acres
                FROM wilson_table_vi
                WHERE blm_tribe_name = %s
            """, [tribe])
            wrow = cur.fetchone()
            if wrow:
                wilson_data = {
                    "reservation": wrow["reservation_name"],
                    "original_acres": int(wrow["original_area_acres"]) if wrow["original_area_acres"] else 0,
                    "allotment_acreage": int(wrow["allotment_acreage"]) if wrow["allotment_acreage"] else 0,
                    "land_alienated": int(wrow["land_alienated_acres"]) if wrow["land_alienated_acres"] else 0,
                    "allotments_1934": int(wrow["total_allotments_made"]) if wrow["total_allotments_made"] else 0,
                }

        # Murray Memorandum 1947-1957 data (if tribe selected)
        murray_data = None
        if tribe:
            cur.execute("""
                SELECT agency, area_office,
                    individual_acres_1947, individual_acres_1957,
                    individual_increase, individual_decrease,
                    tribal_acres_1947, tribal_acres_1957,
                    tribal_increase, tribal_decrease
                FROM murray_comparative
                WHERE blm_tribe_name = %s
            """, [tribe])
            mrow = cur.fetchone()
            if mrow:
                murray_data = {
                    "agency": mrow["agency"],
                    "area_office": mrow["area_office"],
                    "individual_1947": int(mrow["individual_acres_1947"]) if mrow["individual_acres_1947"] else 0,
                    "individual_1957": int(mrow["individual_acres_1957"]) if mrow["individual_acres_1957"] else 0,
                    "individual_loss": int(mrow["individual_decrease"]) if mrow["individual_decrease"] else 0,
                    "individual_gain": int(mrow["individual_increase"]) if mrow["individual_increase"] else 0,
                    "tribal_1947": int(mrow["tribal_acres_1947"]) if mrow["tribal_acres_1947"] else 0,
                    "tribal_1957": int(mrow["tribal_acres_1957"]) if mrow["tribal_acres_1957"] else 0,
                }
                # Also get transaction count and total acres removed
                cur.execute("""
                    SELECT SUM(transaction_count) as total_transactions
                    FROM murray_transactions
                    WHERE blm_tribe_name = %s
                """, [tribe])
                txn = cur.fetchone()
                if txn and txn["total_transactions"]:
                    murray_data["transactions"] = int(txn["total_transactions"])
                cur.execute("""
                    SELECT acres_removed FROM murray_agency_removal
                    WHERE blm_tribe_name = %s
                """, [tribe])
                rem = cur.fetchone()
                if rem and rem["acres_removed"]:
                    murray_data["acres_removed"] = int(rem["acres_removed"])

        total = trust_count + fee_count + other_count

        # FR forced fee claims as sub-flow of Fee
        # Remaining fee = fee patents not accounted for by FR claims
        fee_other = fee_count - fr_forced_claims if fr_forced_claims < fee_count else 0

        # Build Sankey nodes and links
        nodes = [
            {"id": "all", "label": f"All Patents ({total:,})"},
            {"id": "trust", "label": f"Trust ({trust_count:,})"},
            {"id": "fee", "label": f"Fee ({fee_count:,})"},
            {"id": "other", "label": f"Other ({other_count:,})"},
            {"id": "trust_remained", "label": f"Remained in Trust ({trust_remained:,})"},
            {"id": "trust_converted", "label": f"Later Converted ({trust_converted:,})"},
            {"id": "fee_from_trust", "label": f"From Trust ({fee_with_trust_origin:,})"},
            {"id": "fee_direct", "label": f"Direct Fee ({fee_direct:,})"},
        ]

        links = [
            {"source": "all", "target": "trust", "value": trust_count},
            {"source": "all", "target": "fee", "value": fee_count},
            {"source": "all", "target": "other", "value": other_count},
            {"source": "trust", "target": "trust_remained", "value": trust_remained},
            {"source": "trust", "target": "trust_converted", "value": trust_converted},
            {"source": "fee", "target": "fee_from_trust", "value": fee_with_trust_origin},
            {"source": "fee", "target": "fee_direct", "value": fee_direct},
        ]

        # Add FR forced fee claims as sub-flow of Fee (if any)
        if fr_forced_claims > 0:
            nodes.append({"id": "fr_forced", "label": f"FR Forced Fee Claims ({fr_forced_claims:,})"})
            nodes.append({"id": "fee_other", "label": f"Other Fee ({fee_other:,})"})
            links.append({"source": "fee", "target": "fr_forced", "value": fr_forced_claims})
            links.append({"source": "fee", "target": "fee_other", "value": fee_other})

        # Remove zero-value links and their orphan nodes
        links = [l for l in links if l["value"] > 0]
        used_ids = set()
        for l in links:
            used_ids.add(l["source"])
            used_ids.add(l["target"])
        nodes = [n for n in nodes if n["id"] in used_ids]

        return jsonify({
            "nodes": nodes,
            "links": links,
            "stats": {
                "total": total,
                "trust": trust_count,
                "trust_remained": trust_remained,
                "trust_converted": trust_converted,
                "fee": fee_count,
                "fee_with_trust_origin": fee_with_trust_origin,
                "fee_direct": fee_direct,
                "other": other_count,
                "fr_total": fr_total,
                "fr_forced_claims": fr_forced_claims,
                "fr_sec_claims": fr_sec_claims,
                "fr_linked": fr_linked,
                "fr_unlinked": fr_unlinked,
                "timing": {
                    "count": timing["cnt"],
                    "avg_years": round(timing["avg_years"], 1) if timing["avg_years"] else None,
                    "median_years": round(timing["median_years"], 1) if timing["median_years"] else None,
                    "min_years": round(timing["min_years"], 1) if timing["min_years"] is not None else None,
                    "max_years": round(timing["max_years"], 1) if timing["max_years"] is not None else None,
                    "fast": timing["fast_conversions"],
                    "medium": timing["medium_conversions"],
                    "slow": timing["slow_conversions"],
                } if timing["cnt"] > 0 else None,
                "acreage": {
                    "trust_acres": int(acreage["trust_acres"]) if acreage["trust_acres"] else 0,
                    "fee_acres": int(acreage["fee_acres"]) if acreage["fee_acres"] else 0,
                    "avg_trust_acres": float(acreage["avg_trust_acres"]) if acreage["avg_trust_acres"] else 0,
                    "avg_fee_acres": float(acreage["avg_fee_acres"]) if acreage["avg_fee_acres"] else 0,
                    "shrunk": acreage["shrunk"],
                    "same": acreage["same"],
                    "grew": acreage["grew"],
                    "by_speed": acreage_by_speed,
                    "top_tribes": top_tribes_acreage,
                } if acreage["trust_acres"] else None,
                "wilson": wilson_data,
                "murray": murray_data,
            },
        })
    finally:
        conn.close()


@app.route("/claims-rate")
def claims_rate():
    """Forced fee claims vs fee patents by reservation."""
    return render_template("claims_rate.html")


@app.route("/api/claims-rate")
def api_claims_rate():
    """JSON API: per-tribe fee patents vs forced fee claims."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Build tribe name mapping from FR claims -> BLM preferred_name
        # using the linked patents as ground truth
        cur.execute("""
            SELECT fr.tribe_identified as fr_name,
                b.preferred_name as blm_name,
                COUNT(DISTINCT fr.id) as link_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            JOIN blm_allotment_patents b
                ON ffp.patents_accession_number = b.accession_number
            WHERE b.preferred_name IS NOT NULL
            GROUP BY fr.tribe_identified, b.preferred_name
            ORDER BY fr.tribe_identified, link_count DESC
        """)
        # For each FR tribe, pick the BLM name with most links
        fr_to_blm = {}
        for row in cur.fetchall():
            fr_name = row["fr_name"]
            if fr_name not in fr_to_blm:
                fr_to_blm[fr_name] = row["blm_name"]

        # Manual overrides for FR names that map to wrong/small BLM tribes
        fr_to_blm.update({
            "Potawatomi": "Citizen Potawatomi",
            "Citizen Potawatomi (OK)": "Citizen Potawatomi",
            "Kiowa, Comanche, Apache": "Comanche",  # combined reservation
            "Kiowa": "Kiowa",
            "Flandreau Santee Sioux": "Santee Sioux",
            "Fort Belknap (Gros Ventre-Assiniboine)": "Assiniboine And Gros Ventre",
            "Fort Peck (Assiniboine-Sioux)": "Assiniboine And Sioux",
            "Sisseton-Wahpeton": "Sisseton\u2013Wahpeton Oyate",
            "Mission Indians (CA)": None,  # skip — too fragmented
            "Michigan (other)": None,
        })

        # FR claims per tribe (using FR tribe names, mapped to BLM names)
        cur.execute("""
            SELECT tribe_identified,
                COUNT(*) as total_claims,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') as forced_claims,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%SECRETARIAL%%') as sec_claims
            FROM federal_register_claims
            GROUP BY tribe_identified
        """)
        fr_by_tribe = {}
        for row in cur.fetchall():
            blm_name = fr_to_blm.get(row["tribe_identified"], row["tribe_identified"])
            if blm_name is None:
                continue  # skip unmappable tribes
            if blm_name not in fr_by_tribe:
                fr_by_tribe[blm_name] = {"total_claims": 0, "forced_claims": 0,
                                         "sec_claims": 0, "fr_names": []}
            fr_by_tribe[blm_name]["total_claims"] += row["total_claims"]
            fr_by_tribe[blm_name]["forced_claims"] += row["forced_claims"]
            fr_by_tribe[blm_name]["sec_claims"] += row["sec_claims"]
            fr_by_tribe[blm_name]["fr_names"].append(row["tribe_identified"])

        # BLM patent counts per tribe
        cur.execute(f"""
            SELECT preferred_name,
                COUNT(*) as total_patents,
                COUNT(*) FILTER (WHERE authority IN %s OR forced_fee = 'True') as fee_patents,
                COUNT(*) FILTER (WHERE authority IN %s AND forced_fee = 'False') as trust_patents,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_fee_patents
            FROM blm_allotment_patents
            WHERE preferred_name IS NOT NULL
            GROUP BY preferred_name
        """, [FEE_AUTHORITIES, TRUST_AUTHORITIES])

        tribes = []
        for row in cur.fetchall():
            name = row["preferred_name"]
            fr = fr_by_tribe.get(name, {"total_claims": 0, "forced_claims": 0,
                                         "sec_claims": 0, "fr_names": []})
            fee = row["fee_patents"]
            if fee < 20:
                continue
            tribes.append({
                "tribe": name,
                "fr_names": fr["fr_names"],
                "total_patents": row["total_patents"],
                "trust_patents": row["trust_patents"],
                "fee_patents": fee,
                "forced_fee_patents": row["forced_fee_patents"],
                "forced_claims": fr["forced_claims"],
                "total_claims": fr["total_claims"],
                "claim_rate": min(round(fr["forced_claims"] / fee * 100, 1), 100.0) if fee > 0 else 0,
            })

        tribes.sort(key=lambda t: t["fee_patents"], reverse=True)

        return jsonify({"tribes": tribes})
    finally:
        conn.close()


@app.route("/wilson")
def wilson():
    """Wilson Report (1934) — original reservation acreage context."""
    return render_template("wilson.html")


@app.route("/api/wilson")
def api_wilson():
    """JSON API: Wilson Table VI data joined with BLM patent stats."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Wilson data with BLM tribe mapping
        cur.execute("""
            SELECT
                w.reservation_name,
                w.date_established,
                w.original_area_acres,
                w.total_area_acres,
                w.total_reductions_acres,
                w.total_allotments_made,
                w.allotment_acreage,
                w.land_alienated_acres,
                w.living_allotments_num,
                w.living_total_acres,
                w.deceased_allotments_num,
                w.deceased_total_acres,
                w.tribal_total_acres,
                w.govt_total_acres,
                w.blm_tribe_name,
                w.match_method
            FROM wilson_table_vi w
            ORDER BY w.original_area_acres DESC NULLS LAST
        """)
        wilson_rows = cur.fetchall()

        # BLM patent counts per tribe (for matched reservations)
        cur.execute("""
            SELECT preferred_name,
                COUNT(*) as total_patents,
                COUNT(*) FILTER (WHERE authority IN %s OR forced_fee = 'True') as fee_patents,
                COUNT(*) FILTER (WHERE authority IN %s AND forced_fee = 'False') as trust_patents,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_fee_patents
            FROM blm_allotment_patents
            WHERE preferred_name IS NOT NULL
            GROUP BY preferred_name
        """, [FEE_AUTHORITIES, TRUST_AUTHORITIES])
        blm_stats = {}
        for row in cur.fetchall():
            blm_stats[row["preferred_name"]] = row

        # FR claims per BLM tribe (reuse claims-rate mapping logic)
        cur.execute("""
            SELECT fr.tribe_identified as fr_name,
                b.preferred_name as blm_name,
                COUNT(DISTINCT fr.id) as link_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            JOIN blm_allotment_patents b
                ON ffp.patents_accession_number = b.accession_number
            WHERE b.preferred_name IS NOT NULL
            GROUP BY fr.tribe_identified, b.preferred_name
            ORDER BY fr.tribe_identified, link_count DESC
        """)
        fr_to_blm = {}
        for row in cur.fetchall():
            if row["fr_name"] not in fr_to_blm:
                fr_to_blm[row["fr_name"]] = row["blm_name"]
        fr_to_blm.update({
            "Potawatomi": "Citizen Potawatomi",
            "Citizen Potawatomi (OK)": "Citizen Potawatomi",
            "Kiowa, Comanche, Apache": "Comanche",
            "Kiowa": "Kiowa",
            "Flandreau Santee Sioux": "Santee Sioux",
            "Fort Belknap (Gros Ventre-Assiniboine)": "Assiniboine And Gros Ventre",
            "Fort Peck (Assiniboine-Sioux)": "Assiniboine And Sioux",
            "Sisseton-Wahpeton": "Sisseton\u2013Wahpeton Oyate",
            "Mission Indians (CA)": None,
            "Michigan (other)": None,
        })

        cur.execute("""
            SELECT tribe_identified,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') as forced_claims
            FROM federal_register_claims
            GROUP BY tribe_identified
        """)
        fr_claims_by_blm = {}
        for row in cur.fetchall():
            blm_name = fr_to_blm.get(row["tribe_identified"])
            if blm_name:
                fr_claims_by_blm[blm_name] = fr_claims_by_blm.get(blm_name, 0) + row["forced_claims"]

        # Murray comparative data (1947-1957) keyed by BLM tribe name
        cur.execute("""
            SELECT blm_tribe_name, agency, area_office,
                individual_acres_1947, individual_acres_1957,
                individual_increase, individual_decrease,
                tribal_acres_1947, tribal_acres_1957
            FROM murray_comparative
            WHERE blm_tribe_name IS NOT NULL
        """)
        murray_by_blm = {}
        for row in cur.fetchall():
            murray_by_blm[row["blm_tribe_name"]] = row

        # Murray transaction counts
        cur.execute("""
            SELECT blm_tribe_name, SUM(transaction_count) as total
            FROM murray_transactions
            WHERE blm_tribe_name IS NOT NULL
            GROUP BY blm_tribe_name
        """)
        murray_txn_by_blm = {}
        for row in cur.fetchall():
            murray_txn_by_blm[row["blm_tribe_name"]] = int(row["total"])

        # Build response
        reservations = []
        for w in wilson_rows:
            blm_name = w["blm_tribe_name"]
            blm = blm_stats.get(blm_name, {}) if blm_name else {}

            original = w["original_area_acres"] or 0
            allotted = w["allotment_acreage"] or 0
            alienated = w["land_alienated_acres"] or 0
            allotments_1934 = w["total_allotments_made"] or 0
            living = w["living_allotments_num"] or 0
            deceased = w["deceased_allotments_num"] or 0
            # Use living+deceased as allottee count when it exceeds total_allotments_made,
            # since allotments were subdivided among heirs over time
            allottee_count = max(allotments_1934, living + deceased)

            blm_total = blm.get("total_patents", 0)
            blm_fee = blm.get("fee_patents", 0)
            blm_forced = blm.get("forced_fee_patents", 0)
            fr_claims = fr_claims_by_blm.get(blm_name, 0) if blm_name else 0

            # Alienation rate: land alienated as % of allotted
            alienation_rate = round(alienated / allotted * 100, 1) if allotted > 0 else None

            reservations.append({
                "reservation": w["reservation_name"],
                "date_established": w["date_established"],
                "original_acres": original,
                "allotment_acreage": allotted,
                "land_alienated": alienated,
                "alienation_rate": alienation_rate,
                "allotments_1934": allotments_1934,
                "allottee_count": allottee_count,
                "living_allotments": living,
                "living_acres": w["living_total_acres"] or 0,
                "deceased_allotments": w["deceased_allotments_num"] or 0,
                "deceased_acres": w["deceased_total_acres"] or 0,
                "tribal_acres": w["tribal_total_acres"] or 0,
                "govt_acres": w["govt_total_acres"] or 0,
                "blm_tribe": blm_name,
                "blm_total_patents": blm_total,
                "blm_fee_patents": blm_fee,
                "blm_forced_fee": blm_forced,
                "fr_forced_claims": fr_claims,
                "match_method": w["match_method"],
            })

            # Attach Murray data if available
            m = murray_by_blm.get(blm_name) if blm_name else None
            if m:
                reservations[-1]["murray"] = {
                    "agency": m["agency"],
                    "individual_1947": int(m["individual_acres_1947"]) if m["individual_acres_1947"] else 0,
                    "individual_1957": int(m["individual_acres_1957"]) if m["individual_acres_1957"] else 0,
                    "individual_loss": int(m["individual_decrease"]) if m["individual_decrease"] else 0,
                    "transactions": murray_txn_by_blm.get(blm_name, 0),
                }

        # Summary stats — both matched and all
        matched = [r for r in reservations if r["blm_tribe"]]
        all_original = sum(r["original_acres"] for r in reservations)
        all_allotted = sum(r["allotment_acreage"] for r in reservations)
        all_alienated = sum(r["land_alienated"] for r in reservations)
        matched_original = sum(r["original_acres"] for r in matched)
        matched_allotted = sum(r["allotment_acreage"] for r in matched)
        matched_alienated = sum(r["land_alienated"] for r in matched)

        # Murray summary
        cur.execute("""
            SELECT SUM(individual_acres_1947) as i47, SUM(individual_acres_1957) as i57,
                   SUM(COALESCE(individual_decrease, 0)) - SUM(COALESCE(individual_increase, 0)) as net_loss
            FROM murray_comparative
        """)
        msum = cur.fetchone()
        cur.execute("SELECT SUM(transaction_count) as total FROM murray_transactions")
        mtxn_total = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(DISTINCT agency) as cnt FROM murray_comparative")
        magency_count = cur.fetchone()["cnt"]

        return jsonify({
            "reservations": reservations,
            "summary": {
                "total_reservations": len(reservations),
                "matched_reservations": len(matched),
                "all_original_acres": all_original,
                "all_allotted_acres": all_allotted,
                "all_alienated_acres": all_alienated,
                "matched_original_acres": matched_original,
                "matched_allotted_acres": matched_allotted,
                "matched_alienated_acres": matched_alienated,
                "overall_alienation_rate": round(all_alienated / all_allotted * 100, 1) if all_allotted > 0 else 0,
                "murray_agencies": magency_count,
                "murray_individual_1947": int(msum["i47"]) if msum["i47"] else 0,
                "murray_individual_1957": int(msum["i57"]) if msum["i57"] else 0,
                "murray_net_loss": int(msum["net_loss"]) if msum["net_loss"] else 0,
                "murray_transactions": int(mtxn_total) if mtxn_total else 0,
            }
        })
    finally:
        conn.close()


@app.route("/about")
def about():
    """About This Data page."""
    return render_template("about.html")


# ──────────────────────────────────────────────
# Error handlers
# ──────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=5001)
