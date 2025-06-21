from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import EmailMessage
from django.contrib import messages
from django.template.loader import render_to_string
from django.conf import settings
import datetime
import json
from urllib.parse import quote
from carts.models import CartItem
from store.models import Product
from .forms import OrderForm
from .models import Order, Payment, OrderProduct

# WhatsApp Configuration
ADMIN_WHATSAPP_NUMBER = getattr(settings, 'ADMIN_WHATSAPP_NUMBER', '91')
ADMIN_EMAIL = getattr(settings, 'ADMIN_EMAIL', 'eagritraders2025@gmail.com')
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
                payment_id=f"WA-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                payment_method='WhatsApp',
                amount_paid=order.order_total,
                status='Pending'
            )

            # Update order status
            order.payment = payment
            order.is_ordered = True
            order.status = 'Sent to admin, admin will contact you shortly!'
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

            # Prepare order details
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

            # Create WhatsApp message
            whatsapp_message = f"""
🛍️ *NEW ORDER NOTIFICATION* 🛍️
--------------------------------
*Order #:* {order.order_number}
*Customer:* {order.full_name()}
*Phone:* {order.phone}
*Email:* {order.email}
*Total:* ₹{order.order_total:.2f}
*Date:* {order.created_at.strftime('%d %b %Y %I:%M %p')}
--------------------------------
*ITEMS:*
{"\n".join(product_lines)}
--------------------------------
*ADDRESS:*
{order.full_address()}
--------------------------------
*NOTE:*
{order.order_note if order.order_note else 'None'}
"""

            encoded_message = quote(whatsapp_message)

# Create WhatsApp link (for normal app instead of web)
            whatsapp_url = f"https://wa.me/{ADMIN_WHATSAPP_NUMBER}?text={encoded_message}"
            
            # First verify WhatsApp message can be sent
            whatsapp_sent = True  # We assume success since we're just generating a link
            
            # Only send email if WhatsApp message was successfully prepared
            email_sent = False
            email_error = None
            
            if whatsapp_sent:
                try:
                    email_subject = f'Order Confirmation #{order.order_number}'
                    
                    # Load email template with fallback
                    try:
                        template = render_to_string(
                            'orders/order_received_email.html',
                            {
                                'user': request.user,
                                'order': order,
                                'order_items': order_items,
                                'admin_contact': ADMIN_WHATSAPP_NUMBER,
                                'admin_email': ADMIN_EMAIL
                            }
                        )
                    except Exception as e:
                        email_error = f"Template error: {str(e)}"
                        template = f"""
                        <html>
                        <body>
                        <p>Hi {request.user.first_name},</p>
                        <p>YOUR ORDER HAS BEEN RECEIVED</p>
                        <p>Order Number: {order.order_number}</p>
                        <p>Total: ₹{order.order_total:.2f}</p>
                        <p>We'll contact you shortly on WhatsApp at {ADMIN_WHATSAPP_NUMBER}</p>
                        </body>
                        </html>
                        """

                    # Create and send email
                    email = EmailMessage(
                        email_subject,
                        template,
                        settings.DEFAULT_FROM_EMAIL,
                        [order.email],  # primary recipient
                        [ADMIN_EMAIL],  # bcc to admin
                        reply_to=[ADMIN_EMAIL],
                        headers={'Message-ID': f'order-{order.order_number}'}
                    )
                    email.content_subtype = "html"
                    
                    # Send email
                    email.send(fail_silently=False)
                    email_sent = True
                    print("=== Email sent successfully after WhatsApp message ===")
                    
                except Exception as e:
                    email_error = str(e)
                    print(f"\n=== EMAIL SENDING FAILED ===")
                    print(f"Error: {email_error}")
                    import traceback
                    traceback.print_exc()
            else:
                email_error = "WhatsApp message not sent, skipping email"

            response_data = {
                'status': 'success',
                'order_number': order.order_number,
                'payment_id': payment.payment_id,
                'whatsapp_url': whatsapp_url,
                'whatsapp_sent': whatsapp_sent,
                'email_sent': email_sent
            }
            
            if email_error and settings.DEBUG:
                response_data['email_error'] = email_error

            return JsonResponse(response_data)

        except Exception as e:
            print("\n=== SERVER ERROR ===")
            import traceback
            traceback.print_exc()
            print(f"Error: {str(e)}")
            print("====================")
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
            
            # Create WhatsApp cancellation message
            whatsapp_message = f"""
❌ *ORDER CANCELLATION* ❌
--------------------------------
*Order #:* {order.order_number}
*Customer:* {order.full_name()}
*Phone:* {order.phone}
*Email:* {order.email}
*Total:* ₹{order.order_total:.2f}
*Date:* {order.created_at.strftime('%d %b %Y %I:%M %p')}
--------------------------------
*REASON:*
{reason}
"""

            # URL encode the message
            encoded_message = quote(whatsapp_message)
            
            # Create WhatsApp Web link
            whatsapp_url = f"https://web.whatsapp.com/send?phone={ADMIN_WHATSAPP_NUMBER}&text={encoded_message}"
            
            # Send cancellation email to customer
            try:
                email_subject = f'Order Cancellation #{order.order_number}'
                email_body = f"""
Dear {order.full_name()},

Your order #{order.order_number} has been cancelled as per your request.

Cancellation Reason: {reason}

If you didn't request this cancellation or need any assistance, please contact us at {ADMIN_EMAIL} or +91 {ADMIN_WHATSAPP_NUMBER}.

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
            messages.info(request, 'Please inform the admin about your cancellation via WhatsApp.')
        else:
            messages.warning(request, 'This order is already cancelled.')
            
    return redirect('my_orders')