from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, make_response
from forms import ProductForm, CustomerForm
from models import Product, ProductVariant, Customer, Invoice, InvoiceItem, User
from extensions import db
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from datetime import datetime, date, timedelta
from xhtml2pdf import pisa
from datetime import datetime
from io import TextIOWrapper, BytesIO, StringIO
import csv
from indic_transliteration.sanscript import transliterate, SCHEMES
from indic_transliteration import sanscript
from flask_login import current_user, login_required
from functools import wraps
from flask_login import LoginManager
from flask_login import login_user, logout_user
from flask import jsonify

app = Flask(__name__, template_folder='../templates')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'secret'
app.config['SESSION_TYPE'] = 'filesystem'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

db.init_app(app)

# ---------------- Admin Guard ----------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

from flask_login import login_user, logout_user

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('home'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html') 

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('login'))
# ---------------- Home ----------------
@app.route('/')
@login_required
@admin_required
def home():
    invoices = Invoice.query.order_by(Invoice.date.desc()).all()  
    products = Product.query.all()
    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)
    low_stock_variants = ProductVariant.query.filter(ProductVariant.stock <= 5).all()
    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()

    if last_invoice and isinstance(last_invoice.date, str):
        try:
            last_invoice.date = datetime.fromisoformat(last_invoice.date)
        except ValueError:
            last_invoice.date = None

    return render_template(
        'home.html',
        products=products,
        cart_items=cart_items,
        total=total,
        low_stock_variants=low_stock_variants,
        last_invoice=last_invoice
    )

@app.route('/search_product')
def search_product():
    query = request.args.get('q', '').strip().lower()
    starts_with_results = []
    contains_results = []

    if query:
        products = Product.query.all()
        for product in products:
            english_name = product.name.lower()
            tamil_name = (product.tamil_name or '').lower()
            romanized_name = (product.romanized_name or '').lower()

            # Combined search space
            combined = f"{english_name} {tamil_name} {romanized_name}"

            if (
                english_name.startswith(query)
                or tamil_name.startswith(query)
                or romanized_name.startswith(query)
            ):
                starts_with_results.append(product)
            elif query in combined:
                contains_results.append(product)

    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)

    return render_template(
        'search.html',
        query=query,
        starts_with_results=starts_with_results,
        contains_results=contains_results,
        cart_items=cart_items,
        total=total
    )

@app.route('/suggest_products')
def suggest_products():
    query = request.args.get('query', '').strip().lower()

    if not query:
        return jsonify([])

    matches = Product.query.filter(
        or_(
            func.lower(Product.name).contains(query),
            func.lower(Product.tamil_name).contains(query),
            func.lower(Product.romanized_name).contains(query)
        )
    ).all()

    suggestions = [{"id": p.id, "name": p.name} for p in matches]
    return jsonify(suggestions)

# ---------------- Product --------------------
@app.route('/stock')
@login_required
@admin_required
def stock():
    query = request.args.get('search', '').strip().lower()

    if query:
        products = Product.query.filter(
            (Product.name.ilike(f'%{query}%')) |
            (Product.tamil_name.ilike(f'%{query}%')) |
            (Product.romanized_name.ilike(f'%{query}%'))
        ).all()
    else:
        products = Product.query.all()

    return render_template('stock.html', products=products, search_query=query)

# ---------------- Add Product ----------------
@login_required
@admin_required
@app.route('/add_products', methods=['GET', 'POST'])
def add_product():
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(name=form.name.data.strip(), tamil_name=form.tamil_name.data.strip())
        db.session.add(product)
        db.session.commit()

        for variant_form in form.variants:
            if variant_form.unit.data and variant_form.price.data:
                variant = ProductVariant(
                    product_id=product.id,
                    unit=variant_form.unit.data.strip(),
                    price=variant_form.price.data,
                    stock=variant_form.stock.data
                )
                db.session.add(variant)
        db.session.commit()
        flash("Product with variants added!", "success")
        return redirect(url_for('home'))
    return render_template('add_product.html', form=form)

# ---------------- Edit Product ----------------
@login_required
@admin_required
@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)

    form = ProductForm(obj=product)
    if request.method == 'GET':
        form.variants.entries.clear()
        for variant in product.variants:
            form.variants.append_entry({
                'unit': variant.unit,
                'price': variant.price,
                'stock': variant.stock
            })

    if form.validate_on_submit():
        product.name = form.name.data
        product.tamil_name = form.tamil_name.data
        db.session.commit()

        ProductVariant.query.filter_by(product_id=product.id).delete()
        for variant_form in form.variants:
            variant = ProductVariant(
                product_id=product.id,
                unit=variant_form.unit.data,
                price=variant_form.price.data,
                stock=variant_form.stock.data
            )
            db.session.add(variant)
        db.session.commit()
        flash("Product updated", "success")
        return redirect(url_for('home'))

    return render_template('edit.html', form=form)

# ---------------- Delete Product ----------------
@login_required
@admin_required
@app.route('/delete_product/<int:product_id>')
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted", "info")
    return redirect(url_for('home'))

# ---------------- Upload Products CSV ----------------
@login_required
@admin_required
@app.route('/upload-products', methods=['GET', 'POST'])
def upload_products():
    if request.method == 'POST':
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            flash("Only CSV files allowed", "danger")
            return redirect(url_for('upload_products'))

        reader = csv.DictReader(TextIOWrapper(file.stream,  encoding='utf-8'))
        for row in reader:
            name = row['name'].strip()
            tamil_name = row.get('tamil_name', '').strip()
            romanized_name = row.get('romanized_name', '').strip()
            unit = row['unit'].strip()

            try:
                price = float(row['price'])
                stock = float(row.get('stock', 0))
            except ValueError:
                continue

            product = Product.query.filter_by(name=name).first()
            if not product:
                product = Product(name=name, tamil_name=tamil_name, romanized_name=romanized_name)
                db.session.add(product)
                db.session.flush()

            if not ProductVariant.query.filter_by(product_id=product.id, unit=unit).first():
                variant = ProductVariant(product_id=product.id, unit=unit, price=price, stock=stock)
                db.session.add(variant)

        db.session.commit()
        flash("CSV uploaded successfully", "success")
        return redirect(url_for('home'))

    return render_template('upload_products.html')

# ---------------- Cart ----------------
@app.route('/add_to_cart_with_quantity', methods=['POST'])
def add_to_cart_with_quantity():
    variant_id = request.form.get('variant_id')
    quantity = request.form.get('quantity', 1)

    if not variant_id:
        flash("Invalid variant selected.", "danger")
        return redirect(url_for('home'))

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        flash("Invalid quantity entered.", "danger")
        return redirect(url_for('home'))

    # Ensure the variant exists
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        flash("Product variant not found.", "danger")
        return redirect(url_for('home'))

    # Optional: Check stock availability before adding
    if variant.stock is not None:
        cart = session.get('cart', {})
        current_qty = cart.get(str(variant_id), 0)
        if current_qty + quantity > variant.stock:
            flash(f"Only {variant.stock - current_qty} left in stock.", "warning")
            return redirect(request.referrer or url_for('home'))

    # Add to cart
    cart = session.get('cart', {})
    cart[str(variant_id)] = cart.get(str(variant_id), 0) + quantity
    session['cart'] = cart
    session.modified = True

    flash("Item added to cart", "success")
    return redirect(request.referrer or url_for('home'))

@app.route('/add_to_cart/<int:variant_id>')
def add_to_cart(variant_id):
    cart = session.get('cart', {})
    cart[str(variant_id)] = cart.get(str(variant_id), 0) + 1
    session['cart'] = cart
    session.modified = True
    flash("Item added to cart", "success")
    return redirect(request.referrer or url_for('home'))

@app.route('/view_cart')
def view_cart():
    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)
    customers = Customer.query.all()
    return render_template('cart.html', cart_items=cart_items, total=total, customers=customers)

@app.route('/increase_quantity/<int:variant_id>')
def increase_quantity(variant_id):
    cart = session.get('cart', {})
    cart[str(variant_id)] = cart.get(str(variant_id), 0) + 1
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/decrease_quantity/<int:variant_id>')
def decrease_quantity(variant_id):
    cart = session.get('cart', {})
    if cart.get(str(variant_id), 0) > 1:
        cart[str(variant_id)] -= 1
    else:
        cart.pop(str(variant_id), None)
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/remove_from_cart/<int:variant_id>')
def remove_from_cart(variant_id):
    session['cart'].pop(str(variant_id), None)
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/clear_cart')
def clear_cart():
    session['cart'] = {}
    session.modified = True
    return redirect(url_for('view_cart'))

# ---------------- Checkout ----------------
@app.route('/checkout_customer', methods=['POST'])
def checkout_customer():
    customer_id = request.form.get('customer_id')
    return redirect(url_for('checkout', customer_id=customer_id))

@app.route('/checkout/<int:customer_id>')
def checkout(customer_id):
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty", "warning")
        return redirect(url_for('view_cart'))

    customer = Customer.query.get_or_404(customer_id)
    total = 0

    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
    new_bill_no = f"BILL-{(int(last_invoice.bill_no.split('-')[-1]) + 1) if last_invoice else 1:03d}"

    invoice = Invoice(customer_id=customer.id, total=0, bill_no=new_bill_no)
    db.session.add(invoice)
    db.session.commit()

    for variant_id, qty in cart.items():
        variant = ProductVariant.query.get(int(variant_id))
        if variant and variant.stock >= qty:
            subtotal = variant.price * qty
            total += subtotal
            invoice_item = InvoiceItem(invoice_id=invoice.id, variant_id=variant.id, quantity=qty, price=subtotal)
            db.session.add(invoice_item)
            variant.stock -= qty
        else:
            flash(f"Insufficient stock for {variant.product.name} ({variant.unit})", "danger")
            return redirect(url_for('view_cart'))

    invoice.total = total
    db.session.commit()
    session['cart'] = {}
    return redirect(url_for('generate_invoice', invoice_id=invoice.id))

@app.route('/checkout_by_mobile', methods=['POST'])
def checkout_by_mobile():
    phone = request.form.get('phone', '').strip()
    if not phone or not phone.isdigit() or len(phone) != 10:
        flash("Please enter a valid 10-digit mobile number.")
        return redirect(url_for('view_cart'))

    customer = Customer.query.filter_by(phone=phone).first()

    if not customer:
        customer = Customer(name=f"Customer {phone}", phone=phone)
        db.session.add(customer)
        db.session.commit()

    # --- Create invoice like in /checkout ---
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty.")
        return redirect(url_for('view_cart'))

    total = 0
    # Generate custom bill number
    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
    if last_invoice and last_invoice.bill_no:
        try:
            last_number = int(last_invoice.bill_no.split('-')[-1])
            new_bill_no = f"BILL-{last_number + 1:03d}"
        except:
            new_bill_no = "BILL-001"
    else:
        new_bill_no = "BILL-001"

    invoice = Invoice(customer_id=customer.id, total=0, bill_no=new_bill_no)

    db.session.add(invoice)
    db.session.commit()

    for variant_id, qty in cart.items():
        variant = db.session.get(ProductVariant, int(variant_id))
        if variant:
            if variant.stock < qty:
                flash(f"Insufficient stock for {variant.product.name} ({variant.unit})", "danger")
                return redirect(url_for('view_cart'))

            subtotal = variant.price * qty
            total += subtotal

            item = InvoiceItem(
                invoice_id=invoice.id,
                variant_id=variant.id,
                quantity=qty,
                price=subtotal
            )
            db.session.add(item)

            # ✅ Reduce stock
            variant.stock -= qty
    invoice.total = total
    db.session.commit()
    session['cart'] = {}

    return redirect(url_for('generate_invoice', invoice_id=invoice.id))

# ---------------- Invoice----------------
@app.route('/invoices')
@login_required
@admin_required
def all_invoices():
    search_query = request.args.get('search', '').strip()

    query = Invoice.query.join(Invoice.customer).options(joinedload(Invoice.customer))

    if search_query:
        query = query.filter(
            or_(
                Invoice.bill_no.ilike(f"%{search_query}%"),
                Customer.name.ilike(f"%{search_query}%"),
                Customer.phone.ilike(f"%{search_query}%")
            )
        )

    invoices = query.order_by(Invoice.date.desc()).all()

    for invoice in invoices:
        if isinstance(invoice.date, datetime):
            invoice.date_str = invoice.date.strftime('%d-%m-%Y %H:%M')
        else:
            invoice.date_str = invoice.date

    return render_template('invoice_list.html', invoices=invoices, search_query=search_query)

@app.route('/invoice/<int:invoice_id>')
@login_required
@admin_required
def generate_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    items = invoice.items 
    items = [{
        'name': item.variant.product.name,
        'qty': item.quantity,
        'price': item.variant.price,
        'unit': item.variant.unit,
        'subtotal': item.quantity * item.variant.price
    } for item in invoice.items]

    # Calculate totals
    total_items = len(items)
    total_qty = sum(item['qty'] for item in items)
    total = sum(item['subtotal'] for item in items)

    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    html = render_template(
        'invoice.html',
        invoice=invoice,
        items=items,
        total_items=total_items,
        total_qty=total_qty,
        total=total,
        date_str=date_str,   
        time_str=time_str
    )

    # PDF generation
    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result)
    if pisa_status.err:
        return "Error generating PDF"

    response = make_response(result.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=invoice_{invoice.id}.pdf'
    return response

@app.route('/delete_invoice/<int:invoice_id>')
@login_required
@admin_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    
    # Delete invoice items first
    for item in invoice.items:
        variant = item.variant
        variant.stock += item.quantity  # restore stock
        db.session.delete(item)
    
    db.session.delete(invoice)
    db.session.commit()
    
    flash(f"Invoice {invoice.bill_no} deleted.", "info")
    return redirect(url_for('home'))

# ---------------- Sales Report ----------------
@app.route('/sales_report')
@login_required
@admin_required
def sales_report():
    start = request.args.get('start')
    end = request.args.get('end')

    query = Invoice.query
    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d')
            end_dt = datetime.strptime(end, '%Y-%m-%d')
            query = query.filter(Invoice.date.between(start_dt, end_dt))
        except ValueError:
            flash("Invalid date format", "danger")

    invoices = query.order_by(Invoice.date.desc()).all()
    total_sales = sum(i.total for i in invoices)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    daily = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) == today).scalar() or 0
    weekly = db.session.query(func.sum(Invoice.total)).filter(Invoice.date >= week_start).scalar() or 0
    monthly = db.session.query(func.sum(Invoice.total)).filter(Invoice.date >= month_start).scalar() or 0

    return render_template('sales_report.html', invoices=invoices, total_sales=total_sales,
                           daily_total=daily, weekly_total=weekly, monthly_total=monthly)

# ---------------- Download CSV/PDF ----------------
@app.route('/download_sales_csv')
@login_required
@admin_required
def download_sales_csv():
    invoices = Invoice.query.order_by(Invoice.date.desc()).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Invoice ID', 'Customer', 'Date', 'Total'])
    for i in invoices:
        writer.writerow([i.id, i.customer.name, i.date.strftime('%Y-%m-%d'), i.total])
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

@app.route('/download_sales_pdf')
@login_required
@admin_required
def download_sales_pdf():
    invoices = Invoice.query.order_by(Invoice.date.desc()).all()
    html = render_template('sales_report_pdf.html', invoices=invoices)
    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result)
    if pisa_status.err:
        return "PDF generation failed"
    response = make_response(result.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.pdf'
    return response

# ---------------- Utility ----------------
def get_cart_items(cart):
    items = []
    total = 0
    for variant_id, qty in cart.items():
        variant = ProductVariant.query.get(int(variant_id))
        if variant:
            subtotal = variant.price * qty
            items.append({'variant': variant, 'product': variant.product, 'quantity': qty, 'subtotal': subtotal})
            total += subtotal
    return items, total

@app.context_processor
def inject_now():
    return {'current_year': datetime.now().year}

@app.template_filter('format_date')
def format_date(value, format='%d-%m-%Y %H:%M'):
    if isinstance(value, datetime):
        return value.strftime(format)
    return value
# ---------------- Customers ----------------
@app.route('/add_customer', methods=['GET', 'POST'])
@login_required
@admin_required
def add_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer(name=form.name.data.strip(), phone=form.phone.data.strip())
        db.session.add(customer)
        db.session.commit()
        flash("Customer added!", "success")
        return redirect(url_for('customers'))
    return render_template('add_customer.html', form=form)

@app.route('/customers')
@login_required
@admin_required
def customers():
    customers = Customer.query.order_by(Customer.id.desc()).all()
    return render_template('customers.html', customers=customers)

@app.route('/search_customer')
@login_required
@admin_required
def search_customer():
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('customers'))

    customers = Customer.query.filter(
        (Customer.name.ilike(f'%{query}%')) |
        (Customer.phone.ilike(f'%{query}%')) |
        (func.cast(Customer.id, db.String).ilike(f'%{query}%'))
    ).all()

    return render_template('customers.html', customers=customers)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        app.run(debug=True)
