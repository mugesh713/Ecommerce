from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import EmailMessage
from django.contrib import messages
from django.template.loader import render_to_string
from django.conf import settings
from twilio.rest import Client
import datetime
import json
from carts.models import CartItem
from store.models import Product
from .forms import OrderForm
from .models import Order, Payment, OrderProduct

# Twilio Configuration
TWILIO_ACCOUNT_SID = getattr(settings, 'TWILIO_ACCOUNT_SID', 'ACa6752800bd88b39f46aff938c60b88d0')
TWILIO_AUTH_TOKEN = getattr(settings, 'TWILIO_AUTH_TOKEN', 'c2f0d32f58423c7bf835f6f3d6346ba5')
TWILIO_WHATSAPP_NUMBER = getattr(settings, 'TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')
ADMIN_WHATSAPP_NUMBER = getattr(settings, 'ADMIN_WHATSAPP_NUMBER', 'whatsapp:+919942744713')
ADMIN_EMAIL = getattr(settings, 'ADMIN_EMAIL', 'agritraders2025@gmail.com')

@csrf_exempt
def whatsapp_payment(request):
    if request.method == 'POST':
        try:
            # Parse and validate request data
            try:
                body = json.loads(request.body.decode('utf-8'))
                order_number = body.get('orderID')
                if not order_number:
                    raise ValueError("Order ID is required")
            except (json.JSONDecodeError, ValueError) as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Invalid request data: {str(e)}'
                }, status=400)

            # Get and validate order
            try:
                order = Order.objects.get(
                    user=request.user,
                    is_ordered=False,
                    order_number=order_number
                )
            except Order.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Order not found or already processed'
                }, status=404)

            # Create payment record
            payment = Payment.objects.create(
                user=request.user,
                payment_id=f"TWI-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                payment_method='WhatsApp',
                amount_paid=order.order_total,
                status='Pending'
            )

            # Update order status
            order.payment = payment
            order.is_ordered = True
            order.status = 'Sended to the admin,Shortly Admin Will contact You!!'
            order.save()

            # Process order items
            cart_items = CartItem.objects.filter(user=request.user)
            for item in cart_items:
                order_product = OrderProduct.objects.create(
                    order=order,
                    payment=payment,
                    user=request.user,
                    product=item.product,
                    quantity=item.quantity,
                    product_price=item.product.price,
                    ordered=True
                )
                order_product.variations.set(item.variations.all())
                
                # Reduce stock
                product = item.product
                product.stock -= item.quantity
                product.save()

            # Clear cart
            cart_items.delete()

            # Prepare order details for notifications
            order_items = OrderProduct.objects.filter(order=order)
            
            # Format product lines for WhatsApp
            product_lines = []
            for item in order_items:
                product_line = f"• {item.product.product_name} x{item.quantity}"
                if hasattr(item.product, 'power'):
                    product_line += f" (power: {item.product.power}"
                    if hasattr(item.product, 'brand'):
                        product_line += f", brand: {item.product.brand})"
                    else:
                        product_line += ")"
                elif item.variations.exists():
                    product_line += f" ({', '.join(f'{v.variation_category}: {v.variation_value}' for v in item.variations.all())})"
                product_lines.append(product_line)

            # WhatsApp message to ADMIN
            admin_message = f"""
🛍️ *NEW ORDER NOTIFICATION* 🛍️
--------------------------------
*Order #:* {order.order_number}
*Customer:* {order.full_name()}
*Phone:* {order.phone}
*Email:* {order.email}
*Total:* ₹{order.order_total:.2f}
*Date:* {order.created_at.strftime('%d %b %Y')}
--------------------------------
*ITEMS:*
{"\n".join(product_lines)}
--------------------------------
*ADDRESS:*
{order.full_address()}
--------------------------------
*NOTE:*
{order.order_note if order.order_note else 'None'}
--------------------------------
⚠️ Reply:
CONFIRM {order.order_number} to accept
or
CANCEL {order.order_number} [reason] to reject
"""

            # WhatsApp message to CUSTOMER
            customer_message = f"""
New Order Received:

Order Number: {order.order_number}
Customer: {order.full_name()}
Email: {order.email}
Phone: {order.phone}
Total Amount: ₹{order.order_total:.2f}

Order Items:
{"\n".join(product_lines)}

Shipping Address:
{order.full_address()}

Order Note:
{order.order_note if order.order_note else 'None'}
"""

            # Initialize Twilio client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

            # Send to ADMIN
            admin_msg = client.messages.create(
                body=admin_message,
                from_=TWILIO_WHATSAPP_NUMBER,
                to=ADMIN_WHATSAPP_NUMBER
            )

            # Send to CUSTOMER
            customer_phone = order.phone.strip()
            if customer_phone.startswith('+91'):
                customer_phone = customer_phone[3:]
            elif customer_phone.startswith('0'):
                customer_phone = customer_phone[1:]
            whatsapp_customer_number = f"whatsapp:+91{customer_phone}"

            try:
                customer_msg = client.messages.create(
                    body=customer_message,
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=whatsapp_customer_number
                )
            except Exception as e:
                print(f"Failed to send WhatsApp to customer: {str(e)}")

            # Send confirmation email to customer
            try:
                email_subject = f'Order Confirmation #{order.order_number}'
                email_body = render_to_string(
                    'orders/emails/order_received.html',
                    {
                        'user': request.user,
                        'order': order,
                        'order_items': order_items,
                        'admin_contact': '+91 8610743686'
                    }
                )
                email = EmailMessage(
                    email_subject,
                    email_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [order.email],
                    reply_to=[ADMIN_EMAIL]
                )
                email.content_subtype = "html"
                email.send()
            except Exception as e:
                print(f"Email sending error: {str(e)}")

            return JsonResponse({
                'status': 'success',
                'order_number': order.order_number,
                'payment_id': payment.payment_id,
                'whatsapp_status': {
                    'admin': admin_msg.status,
                    'customer': customer_msg.status if 'customer_msg' in locals() else 'Failed'
                },
                'email_sent': True
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Server error: {str(e)}'
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method'
    }, status=405)

def place_order(request, total=0, quantity=0):
    current_user = request.user
    cart_items = CartItem.objects.filter(user=current_user)
    
    if not cart_items.exists():
        messages.warning(request, "Your cart is empty")
        return redirect('store')

    # Calculate totals
    for item in cart_items:
        total += (item.product.price * item.quantity)
        quantity += item.quantity
    
    grand_total = total  # No tax calculation

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            # Create order
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data['first_name']
            data.last_name = form.cleaned_data['last_name']
            data.phone = form.cleaned_data['phone']
            data.email = form.cleaned_data['email']
            data.address_line_1 = form.cleaned_data['address_line_1']
            data.address_line_2 = form.cleaned_data['address_line_2']
            data.city = form.cleaned_data['city']
            data.state = form.cleaned_data['state']
            data.country = form.cleaned_data['country']
            data.order_note = form.cleaned_data['order_note']
            data.order_total = grand_total
            data.tax = 0  # Tax set to 0
            data.ip = request.META.get('REMOTE_ADDR')
            data.save()
            
            # Generate order number
            yr = int(datetime.date.today().strftime('%Y'))
            dt = int(datetime.date.today().strftime('%d'))
            mt = int(datetime.date.today().strftime('%m'))
            d = datetime.date(yr, mt, dt)
            current_date = d.strftime("%Y%m%d")
            data.order_number = current_date + str(data.id)
            data.save()

            context = {
                'order': data,
                'cart_items': cart_items,
                'total': total,
                'tax': 0,  # Tax set to 0
                'grand_total': grand_total,
            }
            return render(request, 'orders/payments.html', context)
        else:
            messages.error(request, "Please correct the errors in the form")
            return redirect('checkout')
    
    return redirect('checkout')

def order_complete(request):
    order_number = request.GET.get('order_number')
    payment_id = request.GET.get('payment_id')
    
    try:
        order = Order.objects.get(order_number=order_number, is_ordered=True)
        payment = Payment.objects.get(payment_id=payment_id)
        ordered_products = OrderProduct.objects.filter(order=order)
        
        subtotal = sum(item.product_price * item.quantity for item in ordered_products)
        
        context = {
            'order': order,
            'ordered_products': ordered_products,
            'order_number': order.order_number,
            'payment_id': payment.payment_id,
            'payment': payment,
            'subtotal': subtotal,
        }
        return render(request, 'orders/order_complete.html', context)
    except (Order.DoesNotExist, Payment.DoesNotExist):
        messages.error(request, "Order not found")
        return redirect('home')

def cancel_order(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        reason = request.POST.get('reason', 'No reason provided')
        
        if order.status != 'Cancelled':
            order.status = 'Cancelled'
            order.order_note = f"{order.order_note or ''}\nCancellation Reason: {reason}"
            order.save()
            
            # Send WhatsApp notification to admin
            try:
                client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                client.messages.create(
                    body=f"Order #{order.order_number} cancelled by customer. Reason: {reason}",
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=ADMIN_WHATSAPP_NUMBER
                )
            except Exception as e:
                print(f"WhatsApp error: {str(e)}")
            
            # Send cancellation email to customer
            try:
                email_subject = f'Order Cancellation #{order.order_number}'
                email_body = f"""
Dear {order.full_name()},

Your order #{order.order_number} has been cancelled as per your request.

Cancellation Reason: {reason}

If you didn't request this cancellation or need any assistance, please contact us at {ADMIN_EMAIL} or +91 8610743686.

Thank you,
Agri Traders Team
"""
                email = EmailMessage(
                    email_subject,
                    email_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [order.email],
                    reply_to=[ADMIN_EMAIL]
                )
                email.send()
            except Exception as e:
                print(f"Cancellation email error: {str(e)}")
            
            messages.success(request, f'Order #{order.order_number} has been cancelled.')
        else:
            messages.warning(request, 'This order is already cancelled.')
            
    return redirect('my_orders')