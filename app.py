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

        return render_template(
            "claim.html",
            claim=claim,
            patents=patents,
            allotment_patents=allotment_patents,
            parcels=parcels,
            trust_links=trust_links,
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
                COUNT(*) as claim_count,
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
