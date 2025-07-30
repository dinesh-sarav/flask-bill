from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, make_response, jsonify
from forms import ProductForm, CustomerForm
from models import Product, ProductVariant, Customer, Invoice, InvoiceItem, User,Settings
from extensions import db
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from datetime import datetime, date, timedelta
from xhtml2pdf import pisa
from flask_login import current_user, login_required, LoginManager, login_user, logout_user
from functools import wraps
from io import BytesIO, StringIO
import csv,io
from flask_wtf import FlaskForm
from flask_mail import Mail 
from flask_mail import Message
from flask_migrate import Migrate
import uuid
import random
from passlib.hash import scrypt
from itsdangerous import URLSafeTimedSerializer

class EmptyForm(FlaskForm):
    pass

def get_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'])

app = Flask(__name__, template_folder='../templates')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'secret'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'dhiyashanthuvan@gmail.com'         
app.config['MAIL_PASSWORD'] = 'pjnuuqcffywokfrs' 
app.config['MAIL_DEFAULT_SENDER'] = 'dhiyashanthuvan@gmail.com'

db.init_app(app)
mail = Mail(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- Admin Guard ----------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    return redirect (url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.email_verified:
                flash("Please verify your email before logging in.", "warning")
                return redirect(url_for('login'))
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for('home') if user.is_admin else url_for('home'))

        flash("Invalid email or password.", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if User.query.filter_by(email=email).first():
            flash("Email already exists", "danger")
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        user.verification_token = str(uuid.uuid4())
        db.session.add(user)
        db.session.commit()

        # Send verification email
        verify_url = url_for('verify_email', token=user.verification_token, _external=True)
        msg = Message("Verify Your Email", recipients=[email])
        msg.body = f"Hi {username}, click this link to verify your email: {verify_url}"
        mail.send(msg)

        flash("Registered successfully. Please check your email to verify your account.", "info")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/verify/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash("Invalid or expired verification link", "danger")
        return redirect(url_for('login'))

    user.email_verified = True
    user.verification_token = None
    db.session.commit()
    flash("Email verified successfully. You can now log in.", "success")
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
        if user:
            serializer = get_serializer()
            token = serializer.dumps(user.email, salt='password-reset')
            user.reset_token = token
            db.session.commit()

            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message("Password Reset", recipients=[email])
            #msg.body = f"Hi {user.username},\n\nYour OTP is: {otp}\nClick the link to reset your password:\n{reset_url}"
            msg.body = f"Hi {user.username},\n\nClick the link below to reset your password:\n{reset_url}"
            mail.send(msg)

            flash("Password reset email sent. check your inbox.", "info")
            return redirect(url_for('login'))
        
        flash("Email not found.", "danger")
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    serializer = get_serializer()
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except Exception:
        flash("Invalid or expired token", "danger")
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first()

    if request.method == 'POST':
        password = request.form['password']
        confirm = request.form['confirm_password']

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('reset_password', token=token))

        user.set_password(password)
        user.reset_token = None
        db.session.commit()

        flash("Password reset successful. Please log in.", "success")
        return redirect(url_for('login'))
        
    return render_template('reset_password.html', token=token)

# ---------------- Home ----------------
@app.route('/')
@login_required
@admin_required
def home():
    active_carts = [] 
    current_cart_id = session.get('current_cart_id') 

    products = Product.query.all()
    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)
    low_stock_variants = ProductVariant.query.filter(ProductVariant.stock <= 5).all()
    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()

    # --- Date conversion for invoices (ensure consistency) ---
    # This block can be removed if invoice.date is always stored as datetime objects.
    # It's better to store dates consistently as datetime in the database.
    # For now, leaving it if your DB has mixed types.
    if last_invoice and isinstance(last_invoice.date, str):
        try:
            last_invoice.date_obj = datetime.fromisoformat(last_invoice.date) # Use a different attribute if needed
        except ValueError:
            last_invoice.date_obj = None
    elif last_invoice:
        last_invoice.date_obj = last_invoice.date # Already a datetime object
    else:
        last_invoice_date_obj = None


    # Calculate daily, weekly, monthly totals for the dashboard
    today = date.today()
    # Assuming your Invoice.date column is stored as datetime objects or convertible
    daily_total = db.session.query(func.sum(Invoice.total)).filter(
        func.date(Invoice.date) == today
    ).scalar() or 0

    week_start = today - timedelta(days=today.weekday())
    weekly_total = db.session.query(func.sum(Invoice.total)).filter(
        func.date(Invoice.date) >= week_start
    ).scalar() or 0

    month_start = today.replace(day=1)
    monthly_total = db.session.query(func.sum(Invoice.total)).filter(
        func.date(Invoice.date) >= month_start
    ).scalar() or 0

    return render_template(
        'home.html',
        active_carts=active_carts, # Still an empty list, or populated if you add persistent cart logic
        current_cart_id=current_cart_id, # Still from session, or populated if you add persistent cart logic
        products=products,
        cart_items=cart_items,
        total=total,
        low_stock_variants=low_stock_variants,
        last_invoice=last_invoice,
        daily_total=daily_total,
        weekly_total=weekly_total,
        monthly_total=monthly_total
    )

# ---------------- Product --------------------
@app.route('/stock')
@login_required
def stock():
    search_query = request.args.get('search', '').strip()
    filter_type = request.args.get('filter', 'all')

    settings = Settings.query.first()
    low_stock_threshold = settings.low_stock_threshold if settings else 10  # fallback

    products = Product.query.all()

    # Filter products based on search
    if search_query:
        products = [
            p for p in products if
            search_query.lower() in (p.name or '').lower() or
            search_query.lower() in (p.tamil_name or '').lower() or
            search_query.lower() in (p.romanized_name or '').lower()
        ]

    # Flatten all variants
    all_variants = [
        variant for product in products for variant in product.variants
    ]

    if filter_type == 'low':
        # Filter variants with stock less than threshold
        filtered_variants = [v for v in all_variants if v.stock < low_stock_threshold]
    elif filter_type == 'high':
        filtered_variants = [v for v in all_variants if v.stock >= low_stock_threshold]
    else:
        filtered_variants = all_variants

    # Re-group filtered variants by product
    product_dict = {}
    for variant in filtered_variants:
        if variant.product_id not in product_dict:
            product_dict[variant.product_id] = {
                'product': variant.product,
                'variants': []
            }
        product_dict[variant.product_id]['variants'].append(variant)

    grouped_products = [
        {
            'product': data['product'],
            'variants': data['variants'],
            'current_stock': sum(v.stock for v in data['variants']),
            'max_stock': sum(v.initial_stock or 0 for v in data['variants'])
        }
        for data in product_dict.values()
    ]

    total_stock = sum(p['current_stock'] for p in grouped_products)

    return render_template(
        'stock.html',
        products=grouped_products,
        total_stock=total_stock,
        search_query=search_query,
        filter_type=filter_type
    )

@app.route('/search_product')
def search_product():
    query = request.args.get('q', '').strip().lower()
    products_found = []

    all_products_with_variants = Product.query.options(db.joinedload(Product.variants)).all()
    if query:
        barcode_variant = ProductVariant.query.filter(ProductVariant.barcode == query).first()
        if barcode_variant:
            products_found.append(barcode_variant.product)

        for product in all_products_with_variants:
            if product not in products_found: # Avoid duplicates
                name = (product.name or '').lower()
                tamil = (product.tamil_name or '').lower()
                roman = (product.romanized_name or '').lower()

                if query in name or query in tamil or query in roman:
                    products_found.append(product)

    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)

    return render_template(
        'home.html', # Redirect search results back to home, so it can display them alongside the dashboard
        products=products_found, # Pass the search results here
        query=query, # Pass the query back for display in the search bar
        cart_items=cart_items,
        total=total,
        # Also pass other home route variables if home.html expects them
        active_carts=[],
        current_cart_id=None,
        low_stock_variants=ProductVariant.query.filter(ProductVariant.stock <= 5).all(),
        last_invoice=Invoice.query.order_by(Invoice.id.desc()).first(),
        daily_total=db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) == date.today()).scalar() or 0,
        weekly_total=db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) >= date.today() - timedelta(days=date.today().weekday())).scalar() or 0,
        monthly_total=db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) >= date.today().replace(day=1)).scalar() or 0
    )

@app.route('/scan_barcode', methods=['POST'])
@login_required # Ensure user is logged in
def scan_barcode():
    barcode = request.form.get('barcode')
    variant = ProductVariant.query.filter_by(barcode=barcode).first()

    if variant:
        # Add to cart directly
        cart = session.get('cart', {})
        cart[str(variant.id)] = cart.get(str(variant.id), 0) + 1
        session['cart'] = cart
        session.modified = True
        flash(f"Product '{variant.product.name}' ({variant.unit}) added from barcode.", "success")
        return redirect(url_for('home')) # Redirect to home to show updated cart
    else:
        flash("No product found for scanned barcode.", "danger")
        return redirect(url_for('home'))

# ---------------- Add Product ----------------
@app.route('/add_products', methods=['GET', 'POST'])
@login_required
@admin_required
def add_product():
    form = ProductForm()

    if request.method == 'POST':
        if form.name.data and form.sold_by.data:
            # Check if product already exists by name (case-insensitive match)
            existing_product = Product.query.filter(
                db.func.lower(Product.name) == form.name.data.strip().lower()
            ).first()

            if existing_product:
                product = existing_product
                flash(f"Product '{product.name}' exists. Adding new variants to it.", "info")
            else:
                product = Product(
                    name=form.name.data.strip(),
                    tamil_name=form.tamil_name.data.strip(),
                    romanized_name=form.romanized_name.data.strip(),
                    sold_by=form.sold_by.data.strip()
                )
                db.session.add(product)
                db.session.flush()  # Ensure product.id is available

            # Handle variants
            variant_index = 0
            while f'variants-{variant_index}-unit' in request.form:
                unit = request.form.get(f'variants-{variant_index}-unit', '').strip()
                price = request.form.get(f'variants-{variant_index}-price')
                stock = request.form.get(f'variants-{variant_index}-stock')
                barcode = request.form.get(f'variants-{variant_index}-barcode', '').strip()

                if unit and price and stock:
                    try:
                        # Optional: check for duplicate barcode if needed
                        if barcode:
                            existing_barcode = ProductVariant.query.filter_by(barcode=barcode).first()
                            if existing_barcode:
                                flash(f"Barcode '{barcode}' already exists. Skipped variant {variant_index + 1}.", "warning")
                                variant_index += 1
                                continue

                        variant = ProductVariant(
                            product_id=product.id,
                            unit=unit,
                            price=float(price),
                            stock=float(stock),
                            barcode=barcode if barcode else None
                        )
                        db.session.add(variant)
                    except ValueError:
                        flash(f"Invalid numeric value in variant {variant_index + 1}", "danger")
                else:
                    flash(f"Variant {variant_index + 1} missing required fields. Skipped.", "warning")

                variant_index += 1

            db.session.commit()

            flash(f"Product '{product.name}' updated with new variants!", "success")
            return redirect(url_for('home'))

        else:
            flash("Product name and unit are required", "danger")

    if request.method == 'GET' and not form.variants.entries:
        form.variants.append_entry()

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
                'stock': variant.stock,
                'barcode': variant.barcode 
            })

    if form.validate_on_submit():
        product.name = form.name.data.strip()
        product.tamil_name = form.tamil_name.data.strip()
        product.romanized_name = form.romanized_name.data.strip()
        product.sold_by = form.sold_by.data.strip()
        
        ProductVariant.query.filter_by(product_id=product.id).delete()
        for variant_form in form.variants:
            if variant_form.unit.data and variant_form.price.data: # Only add if essential fields are present
                variant = ProductVariant(
                    product_id=product.id,
                    unit=variant_form.unit.data.strip(),
                    price=variant_form.price.data,
                    stock=variant_form.stock.data,
                    barcode=variant_form.barcode.data.strip() if variant_form.barcode.data else None
                )
                db.session.add(variant)
        db.session.commit()
        flash("Product updated", "success")
        return redirect(url_for('stock')) 

    return render_template('edit_product.html', form=form, product=product) 

# ---------------- Delete Product ----------------
@login_required
@admin_required
@app.route('/delete_product', methods=['POST'])
def delete_product():
    selected_ids = request.form.get('selected_ids', '')
    ids = [int(pid) for pid in selected_ids.split(',') if pid]

    if not ids:
        flash("No products selected for deletion.", "warning")
        return redirect(url_for('stock'))

    for pid in ids:
        product = Product.query.get(pid)
        if product:
            # Delete associated variants first
            ProductVariant.query.filter_by(product_id=product.id).delete()
            db.session.delete(product)

    db.session.commit()
    flash(f"{len(ids)} product(s) deleted successfully!", "success")
    return redirect(url_for('stock'))

# ---------------- Upload Products CSV ----------------
@login_required
@admin_required
@app.route('/upload_products', methods=['GET', 'POST'])
def upload_products():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash("Please upload a valid CSV file.", "danger")
            return redirect(url_for('upload_products'))

        try:
            stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
            reader = csv.DictReader(stream)

            # Expected columns: name, tamil_name (optional), romanized_name (optional), sold_by (optional), unit, price, stock (optional), barcode (optional)
            required_headers = ['name', 'unit', 'price']
            if not all(header in reader.fieldnames for header in required_headers):
                flash(f"CSV must contain 'name', 'unit', and 'price' columns. Found: {', '.join(reader.fieldnames)}", "danger")
                return redirect(url_for('upload_products'))

            count = 0
            for i, row in enumerate(reader):
                name = row['name'].strip()
                unit = row['unit'].strip()
                
                if not name or not unit:
                    flash(f"Skipping row {i+1}: 'name' or 'unit' cannot be empty.", "warning")
                    continue

                try:
                    price = float(row['price']) if row.get('price') else 0.0
                    stock = float(row.get('stock')) if row.get('stock') else 0.0
                except ValueError:
                    flash(f"Skipping row {i+1}: invalid price or stock. Ensure numeric values.", "warning")
                    continue

                tamil_name = row.get('tamil_name', '').strip()
                romanized_name = row.get('romanized_name', '').strip()
                sold_by = row.get('sold_by', '').strip()
                barcode_raw = row.get('barcode', '').strip()
                barcode = str(barcode_raw) if barcode_raw else None # Store barcode as string, None if empty

                # Create or fetch product
                product = Product.query.filter_by(name=name).first()
                if not product:
                    product = Product(
                        name=name,
                        tamil_name=tamil_name,
                        romanized_name=romanized_name,
                        sold_by=sold_by
                        # No product-level barcode here unless your schema supports it distinctly
                    )
                    db.session.add(product)
                    db.session.flush()  # Ensure product.id is available

                # Create or update variant
                existing_variant = ProductVariant.query.filter_by(
                    product_id=product.id, unit=unit
                ).first()

                if existing_variant:
                    # Update existing variant (e.g., price, stock, barcode)
                    existing_variant.price = price
                    existing_variant.stock = stock
                    existing_variant.barcode = barcode
                else:
                    # Create new variant
                    variant = ProductVariant(
                        product_id=product.id,
                        unit=unit,
                        price=price,
                        stock=stock,
                        barcode=barcode
                    )
                    db.session.add(variant)

                count += 1
                if count % 50 == 0: # Commit in batches
                    db.session.commit()

            db.session.commit() # Final commit for any remaining items
            flash(f"Successfully uploaded {count} product variants from CSV.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error during upload: {str(e)}. Please check your CSV format.", "danger")

        return redirect(url_for('home')) # Redirect to home or stock page

    return render_template('upload_products.html')

# ---------------- Cart ----------------
@app.route('/add_to_cart_with_quantity', methods=['POST'])
@login_required # Ensure user is logged in
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

    variant = ProductVariant.query.get(variant_id)
    if not variant:
        flash("Product variant not found.", "danger")
        return redirect(url_for('home'))

    cart = session.get('cart', {})
    current_qty_in_cart = cart.get(str(variant_id), 0)

    # Check stock availability
    if variant.stock is not None and (current_qty_in_cart + quantity) > variant.stock:
        flash(f"Only {variant.stock - current_qty_in_cart} of {variant.product.name} ({variant.unit}) left in stock.", "warning")
        return redirect(request.referrer or url_for('home'))

    cart[str(variant_id)] = current_qty_in_cart + quantity
    session['cart'] = cart
    session.modified = True

    flash("Item added to cart", "success")
    return redirect(request.referrer or url_for('home'))

@app.route('/add_to_cart/<int:variant_id>')
@login_required # Ensure user is logged in
def add_to_cart(variant_id):
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        flash("Product variant not found.", "danger")
        return redirect(request.referrer or url_for('home'))

    cart = session.get('cart', {})
    current_qty_in_cart = cart.get(str(variant_id), 0)

    # Check stock availability (for single addition)
    if variant.stock is not None and (current_qty_in_cart + 1) > variant.stock:
        flash(f"Only {variant.stock - current_qty_in_cart} of {variant.product.name} ({variant.unit}) left in stock.", "warning")
        return redirect(request.referrer or url_for('home'))

    cart[str(variant_id)] = current_qty_in_cart + 1
    session['cart'] = cart
    session.modified = True
    flash("Item added to cart", "success")
    return redirect(request.referrer or url_for('home'))

@app.route('/view_cart')
@login_required
def view_cart():
    cart = session.get('cart', {})
    cart_items, total = get_cart_items(cart)
    customers = Customer.query.all()
    form = EmptyForm()
    return render_template('cart.html', form=form, cart_items=cart_items, total=total, customers=customers)

@app.route('/increase_quantity/<int:variant_id>')
@login_required
def increase_quantity(variant_id):
    cart = session.get('cart', {})
    current_qty = cart.get(str(variant_id), 0)

    variant = ProductVariant.query.get(variant_id)
    if not variant:
        flash("Product variant not found.", "danger")
        return redirect(url_for('view_cart')) # Or home

    if variant.stock is not None and current_qty + 1 > variant.stock:
        flash(f"Cannot add more. Only {variant.stock - current_qty} left in stock for {variant.product.name}.", "warning")
        return redirect(url_for('view_cart'))

    cart[str(variant_id)] = current_qty + 1
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/decrease_quantity/<int:variant_id>')
@login_required
def decrease_quantity(variant_id):
    cart = session.get('cart', {})
    if cart.get(str(variant_id), 0) > 1:
        cart[str(variant_id)] -= 1
    else:
        cart.pop(str(variant_id), None)
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/remove_from_cart/<int:variant_id>')
@login_required
def remove_from_cart(variant_id):
    session['cart'].pop(str(variant_id), None)
    session.modified = True
    flash("Item removed from cart.", "info")
    return redirect(url_for('view_cart'))

@app.route('/clear_cart')
@login_required
def clear_cart():
    session['cart'] = {}
    session.modified = True
    flash("Cart cleared.", "info")
    return redirect(url_for('view_cart'))

# ---------------- Checkout ----------------
@app.route('/checkout_customer', methods=['POST'])
@login_required
def checkout_customer():
    customer_id = request.form.get('customer_id')
    # Validate customer_id if necessary
    if not customer_id:
        flash("Please select a customer or use the mobile checkout option.", "danger")
        return redirect(url_for('view_cart'))
    return redirect(url_for('checkout', customer_id=customer_id))

'''@app.route('/checkout/<int:customer_id>')
@login_required
def checkout(customer_id):
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty", "warning")
        return redirect(url_for('view_cart'))

    customer = Customer.query.get_or_404(customer_id)

    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
    bill_no = f"BILL-{(int(last_invoice.bill_no.split('-')[-1]) + 1) if last_invoice else 1:03d}"

    invoice = Invoice(
        customer_id=customer.id,
        bill_no=bill_no,
        date=datetime.now(),
        total=0,
        total_items=0,
        total_qty=0
    )

    total_items = 0
    total_qty = 0
    total = 0
    
    for variant_id, qty in cart.items():
        qty = int(qty)
        variant = ProductVariant.query.get(int(variant_id))
        if variant and variant.stock >= qty:
            total += variant.price * qty
            total_items += 1
            total_qty += qty

            db.session.add(InvoiceItem(
                invoice=invoice,
                variant_id=variant.id,
                quantity=qty,
                price=variant.price
            ))

            variant.stock -= qty
        else:
            db.session.rollback()
            flash("Stock issue", "danger")
            return redirect(url_for('view_cart'))

    invoice.total = total
    invoice.total_items = total_items
    invoice.total_qty = total_qty


    db.session.add(invoice)
    db.session.commit()
    
    session['cart'] = {}
    flash("Invoice created", "success")
    return redirect(url_for('generate_invoice', invoice_id=invoice.id))
'''

@app.route('/checkout/<int:customer_id>')
@login_required
def checkout(customer_id):
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty.", "warning")
        return redirect(url_for('view_cart'))

    customer = Customer.query.get_or_404(customer_id)

    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
    bill_no = f"BILL-{(int(last_invoice.bill_no.split('-')[-1]) + 1) if last_invoice else 1:03d}"

    total_items = 0
    total_qty = 0
    total = 0
    invoice_items = []

    for variant_id, qty in cart.items():
        qty = int(qty)
        variant = ProductVariant.query.get(int(variant_id))
        if variant and variant.stock >= qty:
            total += variant.price * qty
            total_items += 1
            total_qty += qty
            invoice_items.append(InvoiceItem(
                variant_id=variant.id,
                quantity=qty,
                price=variant.price
            ))
            variant.stock -= qty
        else:
            flash(f"Insufficient stock for {variant.name if variant else 'Unknown'}", "danger")
            return redirect(url_for('view_cart'))

    invoice = Invoice(
        customer_id=customer.id,
        bill_no=bill_no,
        date=datetime.now(),
        total=total,
        total_items=total_items,
        total_qty=total_qty
    )

    db.session.add(invoice)
    db.session.flush()

    for item in invoice_items:
        item.invoice_id = invoice.id
        db.session.add(item)

    try:
        db.session.commit()
        session['cart'] = {}
        flash("Invoice created successfully!", "success")
        return redirect(url_for('generate_invoice', invoice_id=invoice.id))
    except Exception as e:
        db.session.rollback()
        flash("Invoice failed: " + str(e), "danger")
        return redirect(url_for('view_cart'))

'''@app.route('/checkout_by_mobile', methods=['POST'])
@login_required
def checkout_by_mobile():
    phone = request.form.get('phone', '').strip()
    customer = None

    # ✅ Validate and link customer (if valid phone provided)
    if phone and phone.isdigit() and len(phone) == 10:
        customer = Customer.query.filter_by(phone=phone).first()
        if not customer:
            customer = Customer(name=f"Customer {phone}", phone=phone)
            db.session.add(customer)
            db.session.flush()
    elif phone:
        flash("Invalid mobile number format. Skipping customer linking.", "warning")

    # ✅ Check for cart data
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty.", "warning")
        return redirect(url_for('view_cart'))

    # ✅ Bill number generation
    last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
    bill_no_suffix = int(last_invoice.bill_no.split('-')[-1]) if last_invoice and last_invoice.bill_no and '-' in last_invoice.bill_no else 0
    bill_no = f"BILL-{bill_no_suffix + 1:03d}"

    # ✅ Create Invoice
    invoice = Invoice(
        customer_id=customer.id if customer else None,
        total=0,
        bill_no=bill_no,
        date=datetime.utcnow()
    )
    db.session.add(invoice)
    db.session.flush()

    total_amount = 0
    try:
        for variant_id, qty in cart.items():
            variant = db.session.get(ProductVariant, int(variant_id))
            if not variant or variant.stock is None or variant.stock < qty:
                raise ValueError(f"Insufficient stock for {variant.product.name if variant else 'Unknown Product'}")

            subtotal = variant.price * qty
            total_amount += subtotal

            invoice_item = InvoiceItem(
                invoice_id=invoice.id,
                variant_id=variant.id,
                quantity=qty,
                price=variant.price
            )
            db.session.add(invoice_item)
            variant.stock -= qty

        invoice.total = total_amount
        db.session.commit()
        session['cart'] = {}
        flash(f"✅ Invoice {bill_no} generated successfully!", "success")
        return redirect(url_for('generate_invoice', invoice_id=invoice.id))

    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error: {str(e)}", "danger")
        return redirect(url_for('view_cart'))
'''
@app.route('/checkout_by_mobile', methods=['POST'])
@login_required
def checkout_by_mobile():
    phone = request.form.get('phone', '').strip()
    customer = None

    # 1️⃣ Handle mobile number validation and customer lookup/creation
    if phone:
        if phone.isdigit() and len(phone) == 10:
            customer = Customer.query.filter_by(phone=phone).first()
            if not customer:
                customer = Customer(name=f"Customer {phone}", phone=phone)
                db.session.add(customer)
                db.session.flush()  # Needed to retrieve customer.id
        else:
            flash("Invalid mobile number format. Skipping customer linking.", "warning")

    # 2️⃣ Get and validate cart data
    cart = session.get('cart', {})
    if not cart:
        flash("Cart is empty.", "warning")
        return redirect(url_for('view_cart'))

    # 3️⃣ Calculate totals and prepare invoice items
    total_amount = 0
    total_items = 0
    total_qty = 0
    invoice_items_to_create = []

    try:
        for variant_id, qty in cart.items():
            variant = db.session.get(ProductVariant, int(variant_id))
            if not variant or variant.stock is None or variant.stock < qty:
                raise ValueError(f"Insufficient stock for {variant.product.name if variant else 'Unknown Product'}")

            total_amount += variant.price * qty
            total_items += 1
            total_qty += qty

            invoice_items_to_create.append({
                'variant': variant,
                'quantity': qty,
                'price': variant.price
            })

        # 4️⃣ Generate bill number
        last_invoice = Invoice.query.order_by(Invoice.id.desc()).first()
        last_no = int(last_invoice.bill_no.split('-')[-1]) if last_invoice and last_invoice.bill_no and '-' in last_invoice.bill_no else 0
        bill_no = f"BILL-{last_no + 1:03d}"

        # 5️⃣ Create the invoice
        invoice = Invoice(
            customer_id=customer.id if customer else None,
            total=total_amount,
            bill_no=bill_no,
            date=datetime.utcnow(),
            total_items=total_items,
            total_qty=total_qty
        )
        db.session.add(invoice)
        db.session.flush()

        # 6️⃣ Create invoice items and update stock
        for item in invoice_items_to_create:
            db.session.add(InvoiceItem(
                invoice_id=invoice.id,
                variant_id=item['variant'].id,
                quantity=item['quantity'],
                price=item['price']
            ))
            item['variant'].stock -= item['quantity']

        # 7️⃣ Final commit
        db.session.commit()
        session['cart'] = {}
        flash(f"✅ Invoice {bill_no} generated successfully!", "success")
        return redirect(url_for('generate_invoice', invoice_id=invoice.id))

    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error: {str(e)}", "danger")
        return redirect(url_for('view_cart'))

# ---------------- Invoice----------------
@app.route('/invoices')
@login_required
@admin_required
def all_invoices():
    search_query = request.args.get('search', '').strip()

    query = Invoice.query.options(joinedload(Invoice.customer)) # Always eager load customer
    if search_query:
        # Filter by invoice bill_no, customer name, or customer phone
        query = query.filter(
            or_(
                Invoice.bill_no.ilike(f"%{search_query}%"),
                Customer.name.ilike(f"%{search_query}%"),
                Customer.phone.ilike(f"%{search_query}%")
            )
        )
    invoices = query.order_by(Invoice.date.desc()).all()

    # Ensure invoice.date is a datetime object for formatting
    for invoice in invoices:
        if isinstance(invoice.date, str):
            try:
                invoice.date = datetime.fromisoformat(invoice.date)
            except ValueError:
                invoice.date = None # Or handle error appropriately
        # If it's already datetime, no conversion needed.
        # Format for display in template
        invoice.display_date = invoice.date.strftime('%d-%m-%Y %H:%M') if invoice.date else 'N/A'

    return render_template('invoice_list.html', invoices=invoices, search_query=search_query)

@app.route('/invoice/<int:invoice_id>')
@login_required
@admin_required
def generate_invoice(invoice_id):
    invoice = Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.items).joinedload(InvoiceItem.variant).joinedload(ProductVariant.product)).get_or_404(invoice_id)
    
    items = [{
        'name': item.variant.product.name,
        'qty': item.quantity,
        'price': item.price, # Use the price stored in InvoiceItem (price at time of sale)
        'unit': item.variant.unit,
        'subtotal': item.quantity * item.price # Calculate subtotal based on stored price
    } for item in invoice.items]

    total_items = len(items)
    total_qty = sum(item['qty'] for item in items)
    total = sum(item['subtotal'] for item in items) # This should match invoice.total

    # Ensure invoice.date is a datetime object for formatting in template
    if isinstance(invoice.date, str):
        try:
            invoice.date = datetime.fromisoformat(invoice.date)
        except ValueError:
            invoice.date = None
    
    # Pass date and time strings for consistent display in PDF
    date_str = invoice.date.strftime('%Y-%m-%d') if invoice.date else 'N/A'
    time_str = invoice.date.strftime('%H:%M:%S') if invoice.date else 'N/A'

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

    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result)
    if pisa_status.err:
        flash(f"Error generating PDF for Invoice {invoice.bill_no}: {pisa_status.err}", "danger")
        return "Error generating PDF", 500

    response = make_response(result.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=invoice_{invoice.bill_no}.pdf'
    return response

@app.route('/delete_invoice/<int:invoice_id>', methods=['POST']) # Use POST for deletion
@login_required
@admin_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)

    # Delete invoice items first and restore stock
    for item in invoice.items:
        variant = ProductVariant.query.get(item.variant_id) # Fetch variant directly using ID from item
        if variant: # Only restore stock if variant still exists
            variant.stock = (variant.stock or 0) + item.quantity  # Restore stock, handle None case
        db.session.delete(item)

    db.session.delete(invoice)
    db.session.commit()

    flash(f"Invoice {invoice.bill_no} deleted and stock restored.", "info")
    return redirect(url_for('all_invoices')) # Redirect to the all invoices page

# ---------------- Sales Report ----------------
@app.route('/sales_report')
@login_required
@admin_required
def sales_report():
    start = request.args.get('start')
    end = request.args.get('end')

    query = Invoice.query.options(joinedload(Invoice.customer))
    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d')
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Invoice.date.between(start_dt, end_dt))
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "danger")

    invoices = query.order_by(Invoice.date.desc()).all()
    total_sales = sum(i.total for i in invoices)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    daily_total = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) == today).scalar() or 0
    weekly_total = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) >= week_start).scalar() or 0
    monthly_total = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.date) >= month_start).scalar() or 0

    daily_count = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.date) == today).scalar() or 0
    weekly_count = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.date) >= week_start).scalar() or 0
    monthly_count = db.session.query(func.count(Invoice.id)).filter(func.date(Invoice.date) >= month_start).scalar() or 0

    return render_template(
        'sales_report.html',
        invoices=invoices,
        total_sales=total_sales,
        daily_total=daily_total,
        weekly_total=weekly_total,
        monthly_total=monthly_total,
        daily_count=daily_count,
        weekly_count=weekly_count,
        monthly_count=monthly_count,
        selected_start=start,
        selected_end=end
    )

# ---------------- Download CSV/PDF ----------------
@app.route('/download_sales_csv')
@login_required
@admin_required
def download_sales_csv():
    start = request.args.get('start')
    end = request.args.get('end')
    query = Invoice.query.options(joinedload(Invoice.customer))

    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d')
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Invoice.date.between(start_dt, end_dt))
        except ValueError:
            pass  # Ignore invalid date filters

    invoices = query.order_by(Invoice.date.desc()).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Invoice ID', 'Bill No', 'Customer Name', 'Customer Phone', 'Date', 'Total'])

    for i in invoices:
        customer_name = i.customer.name if i.customer else 'Walk-in Customer'
        customer_phone = i.customer.phone if i.customer else 'N/A'
        writer.writerow([
            i.id,
            i.bill_no,
            customer_name,
            customer_phone,
            i.date.strftime('%Y-%m-%d %H:%M:%S'),
            i.total
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

@app.route('/download_sales_pdf')
@login_required
def download_sales_pdf():
    start = request.args.get('start')
    end = request.args.get('end')
    query = Invoice.query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.items).joinedload(InvoiceItem.variant).joinedload(ProductVariant.product)
    )

    if start and end:
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d')
            end_dt = datetime.strptime(end, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Invoice.date.between(start_dt, end_dt))
        except ValueError:
            pass  # fallback to all

    invoices = query.order_by(Invoice.date.desc()).all()

    invoices_data = []
    for invoice in invoices:
        item_data = []
        for item in invoice.items:
            item_data.append({
                'name': item.variant.product.name,
                'qty': item.quantity,
                'price': item.price,
                'subtotal': item.quantity * item.price
            })

        invoices_data.append({
            'invoice_id': invoice.id,
            'bill_no': invoice.bill_no,
            'customer_name': invoice.customer.name if invoice.customer else 'Walk-in',
            'customer_phone': invoice.customer.phone if invoice.customer else 'N/A',
            'date': invoice.date.strftime('%Y-%m-%d %H:%M:%S'),
            'total': invoice.total,
            'invoice_items': item_data
        })

    html = render_template('sales_report_pdf.html',
                           invoices=invoices_data,
                           current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result)
    if pisa_status.err:
        flash("PDF generation failed", "danger")
        return "PDF generation failed", 500

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
    return {'current_year': datetime.now().year, 'current_user': current_user} # Inject current_user for base.html

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
        # Check for existing phone number before adding
        existing_customer = Customer.query.filter_by(phone=form.phone.data.strip()).first()
        if existing_customer:
            flash("A customer with this phone number already exists.", "warning")
            return render_template('add_customer.html', form=form)

        customer = Customer(name=form.name.data.strip(), phone=form.phone.data.strip())
        db.session.add(customer)
        db.session.commit()
        flash("Customer added successfully!", "success")
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

@app.route('/edit_customer/<int:customer_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerForm(obj=customer)
    if form.validate_on_submit():
        # Check for duplicate phone number, excluding the current customer being edited
        existing_customer = Customer.query.filter(
            Customer.phone == form.phone.data.strip(),
            Customer.id != customer_id
        ).first()
        if existing_customer:
            flash("A customer with this phone number already exists.", "warning")
            return render_template('edit_customer.html', form=form, customer=customer)

        customer.name = form.name.data.strip()
        customer.phone = form.phone.data.strip()
        db.session.commit()
        flash("Customer updated successfully!", "success")
        return redirect(url_for('customers'))
    return render_template('edit_customer.html', form=form, customer=customer)

@app.route('/delete_customer/<int:customer_id>', methods=['POST'])
@login_required
@admin_required
def delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    # Optional: Check if the customer has any invoices before deleting, and prevent if so
    if customer.invoices:
        flash("Cannot delete customer with associated invoices. Delete invoices first.", "danger")
        return redirect(url_for('customers'))
    
    db.session.delete(customer)
    db.session.commit()
    flash("Customer deleted successfully!", "success")
    return redirect(url_for('customers'))

# ---------------- Settings ----------------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    settings = Settings.query.first()
    admin = current_user

    if not settings:
        settings = Settings(
            store_name="",
            store_address="",
            phone="",
            gst_number="",
            invoice_prefix="INV-",
            low_stock_threshold=10,
            currency_symbol="₹"
        )
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        new_email = request.form['admin_email']
        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user and existing_user.id != admin.id:
            flash("This email is already used by another account.", "danger")
            return redirect(url_for('settings'))
        
        # Update settings
        settings.store_name = request.form['store_name']
        settings.store_address = request.form['store_address']
        settings.phone = request.form['phone']
        settings.gst_number = request.form['gst_number']
        settings.invoice_prefix = request.form['invoice_prefix']
        settings.low_stock_threshold = int(request.form['low_stock_threshold'])
        settings.currency_symbol = request.form['currency_symbol']

        # Update admin user fields
        admin.username = request.form['admin_name']
        admin.email = request.form['admin_email']
        new_password = request.form['admin_password']
        if new_password:
            admin.set_password(new_password)

        db.session.commit()
        login_user(admin, fresh=True)
        flash("Settings and admin details updated successfully!", "success")
        return redirect(url_for('settings'))
    
    print("Admin name from DB:", admin.username)
    return render_template("settings.html", settings=settings, admin=admin)

@app.route('/update_stock/<int:variant_id>', methods=['POST'])
@login_required
@admin_required
def update_stock(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    increment = int(request.form.get('increment', 1))  # default +1
    variant.stock += increment
    db.session.commit()
    flash(f'Stock updated for variant {variant.unit}', 'success')
    return redirect(url_for('stock'))

@app.route('/add_stock_by_barcode_inline', methods=['POST'])
@login_required
@admin_required
def add_stock_by_barcode_inline():
    barcode = request.form.get('barcode', '').strip()
    added_stock = request.form.get('added_stock', '').strip()

    if not barcode or not added_stock:
        flash("Please enter both barcode and stock quantity.", "danger")
    else:
        variant = ProductVariant.query.filter_by(barcode=barcode).first()
        if not variant:
            flash("No product found with this barcode.", "warning")
        else:
            try:
                added_qty = float(added_stock)
                variant.stock += added_qty
                db.session.commit()
                flash(f"✅ Added {added_qty} stock to {variant.product.name} ({variant.unit})", "success")
            except ValueError:
                flash("Invalid stock quantity", "danger")

    return redirect(url_for('add_product'))

#-----------------------------------------
@app.route('/admin/verify_otp', methods=['GET', 'POST'])
def admin_verify_otp():
    if request.method == 'POST':
        if request.form['otp'] == session.get('otp'):
            flash("OTP verified. Please reset your password.", "success")
            return redirect(url_for('admin_reset_password'))
        else:
            flash("Invalid OTP.", "danger")
    return render_template('admin_verify_otp.html')

#--------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
