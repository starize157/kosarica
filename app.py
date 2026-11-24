"""Spletna trgovina Košarica."""

from flask import (
    Blueprint,
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import store

app = Flask(__name__)
app.secret_key = "kosarica-lokalni-kljuc"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
)

admin = Blueprint("admin", __name__, url_prefix="/dashboard")


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    return value


def load_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        db = store.read_db()
    except store.StoreError:
        return None
    user = store.get_user(db, user_id)
    if not user:
        session.pop("user_id", None)
    return user


def login_required(view):
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("prijava", naprej=request.path))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@app.context_processor
def inject_globals():
    return {
        "meta": store.META,
        "day_label": store.DAY_LABEL,
        "status_label": store.STATUS_LABEL,
        "group_icon": store.GROUP_ICON,
        "current_user": load_current_user(),
    }


@app.template_filter("sidate")
def sidate_filter(value):
    return store.format_date(value)


@app.template_filter("eur")
def eur_filter(value):
    return f"{int(value)} €"


@app.template_filter("cap")
def cap_filter(value):
    if not value:
        return value
    return value[0].upper() + value[1:]


def remember_user(user):
    session.permanent = True
    session["user_id"] = user["id"]


@app.route("/")
def index():
    return render_template(
        "index.html",
        baskets=store.all_baskets(),
        featured=store.basket_public("srednja"),
        farms=store.FARMS,
        faqs=store.FAQS[:4],
        groups=store.produce_groups(),
        quotes=store.TESTIMONIALS,
    )


@app.route("/kosarice")
def kosarice():
    return render_template("kosarice.html", baskets=store.all_baskets())


@app.route("/kosarica/<size>", methods=["GET", "POST"])
def kosarica(size):
    if size not in store.BASKETS:
        return render_template("404.html"), 404
    basket = store.basket_public(size)
    selected = {}
    draft = session.get("draft") or {}
    if draft.get("size") == size:
        selected = store.swap_map(draft.get("swaps"))
    if request.method == "POST":
        try:
            swaps = store.swaps_from_form(size, request.form)
        except store.StoreError as error:
            flash(str(error))
            selected = store.swap_map(
                [
                    {"remove": item["id"], "add": request.form.get(f"swap_{item['id']}", "")}
                    for item in basket["items"]
                    if request.form.get(f"swap_{item['id']}", "")
                ]
            )
        else:
            session["draft"] = {"size": size, "swaps": swaps}
            session.permanent = True
            return redirect(url_for("narocilo"))
    return render_template(
        "prilagodi.html",
        basket=basket,
        options=store.swap_options(size),
        selected=selected,
        names=store.name_index(),
        action=url_for("kosarica", size=size),
        button="Nadaljuj na dostavo",
    )


@app.route("/kako-deluje")
def kako():
    return render_template("kako.html", faqs=store.FAQS, baskets=store.all_baskets())


@app.route("/kmetije")
def kmetije():
    return render_template("kmetije.html", farms=store.FARMS, groups=store.produce_groups())


@app.route("/pogoji")
def pogoji():
    return render_template("pogoji.html")


@app.route("/prijava", methods=["GET", "POST"])
def prijava():
    naprej = safe_next(request.values.get("naprej"))
    if session.get("user_id") and request.method == "GET":
        return redirect(naprej or url_for("racun"))
    if request.method == "POST":
        try:
            user = store.authenticate(store.read_db(), request.form.get("email"), request.form.get("geslo"))
        except store.StoreError as error:
            flash(str(error))
        else:
            remember_user(user)
            return redirect(naprej or url_for("racun"))
    return render_template("prijava.html", naprej=naprej or "")


@app.route("/registracija", methods=["GET", "POST"])
def registracija():
    naprej = safe_next(request.values.get("naprej"))
    if request.method == "POST":
        try:
            first, last, email, password = store.parse_person(request.form)

            def mutate(db):
                return store.create_user(db, first, last, email, password)

            user = store.update_db(mutate)
        except store.StoreError as error:
            flash(str(error))
        else:
            remember_user(user)
            flash("Račun je odprt. Še naslov, in košarica ima kam priti.")
            return redirect(naprej or url_for("narocilo"))
    return render_template("registracija.html", naprej=naprej or "")


@app.route("/odjava", methods=["POST"])
def odjava():
    session.pop("user_id", None)
    flash("Odjavljen si.")
    return redirect(url_for("index"))


@app.route("/narocilo", methods=["GET", "POST"])
@login_required
def narocilo():
    draft = session.get("draft")
    if not draft or draft.get("size") not in store.BASKETS:
        flash("Najprej izberi velikost košarice.")
        return redirect(url_for("kosarice"))
    try:
        items = store.compose_items(draft["size"], draft.get("swaps"))
    except store.StoreError as error:
        flash(str(error))
        return redirect(url_for("kosarica", size=draft["size"]))
    user = load_current_user()
    sub = store.present_subscription(store.get_subscription(store.read_db(), user["id"]))
    values = store.address_values(user, request.form if request.method == "POST" else None, (sub or {}).get("deliveryDay", ""))
    if request.method == "POST":
        try:
            address, day, phone = store.parse_address(request.form)
            if not day:
                raise store.StoreError("Izberi dan dostave.")

            def mutate(db):
                account = store.get_user(db, user["id"])
                account["address"] = address
                if phone:
                    account["phone"] = phone
                return store.place_subscription(db, user["id"], draft["size"], draft.get("swaps"), day)

            _sub, first = store.update_db(mutate)
        except store.StoreError as error:
            flash(str(error))
        else:
            session.pop("draft", None)
            session["confirmation_id"] = first["id"]
            return redirect(url_for("potrditev"))
    basket = store.basket_public(draft["size"])
    return render_template(
        "narocilo.html",
        basket=basket,
        items=items,
        values=values,
        swaps=draft.get("swaps") or [],
        existing=sub,
    )


@app.route("/potrditev")
@login_required
def potrditev():
    order_id = session.get("confirmation_id")
    if not order_id:
        return redirect(url_for("racun"))
    db = store.read_db()
    order = store.get_order(db, order_id)
    if not order or order["userId"] != session.get("user_id"):
        return redirect(url_for("racun"))
    sub = store.present_subscription(store.get_subscription(db, session["user_id"]))
    return render_template("potrditev.html", order=store.present_order(db, order), subscription=sub)


@app.route("/racun", methods=["GET"])
@login_required
def racun():
    db = store.read_db()
    snapshot = store.account_snapshot(db, session["user_id"])
    sub = snapshot["subscription"]
    swap_form = None
    if sub:
        swap_form = {
            "basket": store.basket_public(sub["size"]),
            "options": store.swap_options(sub["size"]),
            "selected": store.swap_map(sub["swaps"]),
            "names": store.name_index(),
        }
    values = store.address_values(snapshot["user"], day=(sub or {}).get("deliveryDay", ""))
    return render_template("racun.html", snap=snapshot, swap_form=swap_form, values=values)


@app.post("/racun/menjave")
@login_required
def racun_menjave():
    db = store.read_db()
    sub = store.get_subscription(db, session["user_id"])
    if not sub:
        flash("Najprej izberi košarico.")
        return redirect(url_for("kosarice"))
    try:
        swaps = store.swaps_from_form(sub["size"], request.form)

        def mutate(data):
            return store.update_swaps(data, session["user_id"], swaps)

        store.update_db(mutate)
    except store.StoreError as error:
        flash(str(error))
    else:
        flash("Menjave so shranjene za košarice, ki še niso v pakiranju.")
    return redirect(url_for("racun"))


@app.post("/racun/pavza")
@login_required
def racun_pavza():
    db = store.read_db()
    sub = store.get_subscription(db, session["user_id"])
    if not sub:
        return redirect(url_for("kosarice"))
    pause = sub["status"] == "aktivna"

    def mutate(data):
        return store.set_paused(data, session["user_id"], pause)

    try:
        store.update_db(mutate)
    except store.StoreError as error:
        flash(str(error))
    else:
        flash("Naročnina je pavzirana." if pause else "Naročnina spet teče.")
    return redirect(url_for("racun"))


@app.post("/racun/naslov")
@login_required
def racun_naslov():
    try:
        address, _day, phone = store.parse_address(request.form)

        def mutate(data):
            return store.update_address(data, session["user_id"], address, phone)

        store.update_db(mutate)
    except store.StoreError as error:
        flash(str(error))
    else:
        flash("Naslov je posodobljen za košarice, ki še niso na poti.")
    return redirect(url_for("racun"))


@app.post("/racun/dan")
@login_required
def racun_dan():
    try:
        def mutate(data):
            return store.update_day(data, session["user_id"], request.form.get("dan", ""))

        store.update_db(mutate)
    except store.StoreError as error:
        flash(str(error))
    else:
        flash("Dan dostave velja za košarice, ki še niso v pakiranju.")
    return redirect(url_for("racun"))


@admin.before_request
def guard_admin():
    if request.endpoint == "admin.prijava":
        return None
    if not session.get("admin"):
        return redirect(url_for("admin.prijava"))
    return None


@admin.context_processor
def admin_counts():
    if not session.get("admin"):
        return {}
    try:
        db = store.read_db()
    except store.StoreError:
        return {}
    stats = store.overview(db)
    return {"nav_counts": {"narocila": len(db["orders"]), "stranke": len(db["users"]), "dostave": stats["weekBaskets"]}}


@admin.route("/prijava", methods=["GET", "POST"])
def prijava():
    if session.get("admin") and request.method == "GET":
        return redirect(url_for("admin.pregled"))
    if request.method == "POST":
        if store.admin_ok(request.form.get("uporabnik") or "", request.form.get("geslo") or ""):
            session.permanent = True
            session["admin"] = True
            return redirect(url_for("admin.pregled"))
        flash("Napačno uporabniško ime ali geslo.")
    return render_template("dashboard/prijava.html")


@admin.post("/odjava")
def odjava():
    session.pop("admin", None)
    flash("Odjava iz pregleda je uspela.")
    return redirect(url_for("admin.prijava"))


@admin.route("/")
def pregled():
    db = store.read_db()
    return render_template("dashboard/pregled.html", stats=store.overview(db))


@admin.route("/narocila")
def narocila():
    db = store.read_db()
    week = request.args.get("teden")
    if week is None:
        week = store.overview(db)["weekOf"]
    elif week == "vsi":
        week = ""
    try:
        page = int(request.args.get("stran", "1"))
    except ValueError:
        page = 1
    rows = store.filter_orders(
        db,
        query=request.args.get("q", ""),
        status=request.args.get("status", ""),
        size=request.args.get("size", ""),
        week=week,
    )
    return render_template(
        "dashboard/narocila.html",
        result=store.paginate(rows, page),
        weeks=store.week_choices(db),
        filters={
            "q": request.args.get("q", ""),
            "status": request.args.get("status", ""),
            "size": request.args.get("size", ""),
            "teden": week or "vsi",
        },
        statuses=store.STATUS_LABEL,
        baskets=store.BASKETS,
    )


@admin.route("/narocila/<order_id>")
def narocilo(order_id):
    db = store.read_db()
    order = store.get_order(db, order_id)
    if not order:
        return render_template("404.html"), 404
    return render_template("dashboard/narocilo.html", order=store.present_order(db, order))


@admin.post("/narocila/<order_id>/status")
def status(order_id):
    try:
        def mutate(db):
            return store.set_order_status(db, order_id, request.form.get("status", ""))

        store.update_db(mutate)
    except store.StoreError as error:
        flash(str(error))
    else:
        flash("Status je posodobljen.")
    return redirect(safe_next(request.form.get("naprej")) or url_for("admin.narocilo", order_id=order_id))


@admin.route("/stranke")
def stranke():
    db = store.read_db()
    return render_template("dashboard/stranke.html", rows=store.customer_rows(db, request.args.get("q", "")), q=request.args.get("q", ""))


@admin.route("/dostave")
def dostave():
    db = store.read_db()
    week = request.args.get("teden") or store.iso(store.monday_of(store.date.today()))
    known = {choice["value"] for choice in store.week_choices(db)}
    if week not in known:
        week = store.overview(db)["weekOf"]
    board = store.deliveries_for_week(db, week)
    return render_template("dashboard/dostave.html", board=board, weeks=store.week_choices(db), teden=week)


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(store.StoreError)
def missing_db(error):
    return render_template("napaka.html", message=str(error)), 500


app.register_blueprint(admin)

try:
    from workers import wsgi
except ImportError:
    pass
else:
    Default = wsgi.entrypoint(app)


if __name__ == "__main__":
    print("Košarica teče na http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, debug=True)
