from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from carts.models import CartItem
from .forms import OrderForm
import datetime
from .models import Order, Payment, OrderProduct
import json
from store.models import Product
from django.core.mail import EmailMessage
from django.contrib import messages
from django.template.loader import render_to_string
import pywhatkit
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404


@csrf_exempt
def whatsapp_payment(request):
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            order = Order.objects.get(user=request.user, is_ordered=False, order_number=body['orderID'])
            phone_number = order.phone  # Get phone from order
            
            # Create minimal payment record
            payment = Payment(
                user=request.user,
                payment_id=f"WA-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                payment_method='WhatsApp',
                amount_paid=order.order_total,
                status='Pending Confirmation',
            )
            payment.save()

            # Update order status
            order.payment = payment
            order.is_ordered = True
            order.status = 'Accepted'
            order.save()

            # Move cart items to order products
            cart_items = CartItem.objects.filter(user=request.user)
            for item in cart_items:
                orderproduct = OrderProduct()
                orderproduct.order_id = order.id
                orderproduct.payment = payment
                orderproduct.user_id = request.user.id
                orderproduct.product_id = item.product_id
                orderproduct.quantity = item.quantity
                orderproduct.product_price = item.product.price
                orderproduct.ordered = True
                orderproduct.save()

                cart_item = CartItem.objects.get(id=item.id)
                product_variation = cart_item.variations.all()
                orderproduct.variations.set(product_variation)
                orderproduct.save()

                # Reduce product stock
                product = Product.objects.get(id=item.product_id)
                product.stock -= item.quantity
                product.save()

            # Clear cart
            CartItem.objects.filter(user=request.user).delete()

           # Get the ordered items
            order_items = OrderProduct.objects.filter(order=order)

            # Format product name and quantity without bullets or asterisks
            product_lines = "\n".join([f"{item.product.product_name} x{item.quantity}" for item in order_items])

# Final WhatsApp message
            message = f"""
            *New Order Notification* 🛍️
            Order Number: {order.order_number}
            Customer: {order.full_name()}
            Total Amount: ₹{order.order_total}
            Delivery Address: {order.full_address()}

            {product_lines}

            Please confirm this order by replying 'CONFIRM {order.order_number}'
            """

            
            try:
                pywhatkit.sendwhatmsg_instantly(
                    phone_no=f"+91{9942744713}",  # Indian format
                    message=message,
                    wait_time=15,
                    tab_close=True
                )
            except Exception as e:
                print(f"WhatsApp sending failed: {str(e)}")

            # Send confirmation email
            mail_subject = 'Your Order is Pending Confirmation'
            email_message = render_to_string('orders/order_recieved_email.html', {
                'user': request.user,
                'order': order,
            })
            email = EmailMessage(mail_subject, email_message, to=[order.email])
            email.send()

            return JsonResponse({
                'status': 'success',
                'order_number': order.order_number,
                'transID': payment.payment_id,
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method'
    }, status=400)

def place_order(request, total=0, quantity=0):
    current_user = request.user
    cart_items = CartItem.objects.filter(user=current_user)
    cart_count = cart_items.count()
    
    if cart_count <= 0:
        return redirect('store')

    grand_total = 0
    tax = 0
    for cart_item in cart_items:
        total += (cart_item.product.price * cart_item.quantity)
        quantity += cart_item.quantity
    
    tax = (2 * total)/100
    grand_total = total + tax

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data['first_name']
            data.last_name = form.cleaned_data['last_name']
            data.phone = form.cleaned_data['phone']
            data.email = form.cleaned_data['email']
            data.address_line_1 = form.cleaned_data['address_line_1']
            data.address_line_2 = form.cleaned_data['address_line_2']
            data.country = form.cleaned_data['country']
            data.state = form.cleaned_data['state']
            data.city = form.cleaned_data['city']
            data.order_note = form.cleaned_data['order_note']
            data.order_total = grand_total
            data.tax = tax
            data.ip = request.META.get('REMOTE_ADDR')
            data.save()
            
            # Generate order number
            yr = int(datetime.date.today().strftime('%Y'))
            dt = int(datetime.date.today().strftime('%d'))
            mt = int(datetime.date.today().strftime('%m'))
            d = datetime.date(yr, mt, dt)
            current_date = d.strftime("%Y%m%d")
            order_number = current_date + str(data.id)
            data.order_number = order_number
            data.save()

            order = Order.objects.get(user=current_user, is_ordered=False, order_number=order_number)
            context = {
                'order': order,
                'cart_items': cart_items,
                'total': total,
                'tax': tax,
                'grand_total': grand_total,
            }
            return render(request, 'orders/payments.html', context)
    
    return redirect('checkout')

def order_complete(request):
    order_number = request.GET.get('order_number')
    transID = request.GET.get('payment_id')

    try:
        order = Order.objects.get(order_number=order_number, is_ordered=True)
        ordered_products = OrderProduct.objects.filter(order_id=order.id)

        subtotal = 0
        for i in ordered_products:
            subtotal += i.product_price * i.quantity

        payment = Payment.objects.get(payment_id=transID)

        context = {
            'order': order,
            'ordered_products': ordered_products,
            'order_number': order.order_number,
            'transID': payment.payment_id,
            'payment': payment,
            'subtotal': subtotal,
        }
        return render(request, 'orders/order_complete.html', context)
    except (Payment.DoesNotExist, Order.DoesNotExist):
        return redirect('home')


def cancel_order(request, order_id):
    if request.method == 'POST':
        reason = request.POST.get('reason')
        order = get_object_or_404(Order, id=order_id, user=request.user)
        
        if order.status != 'Cancelled':   # Use status field here
            order.status = 'Cancelled'     # Update status to Cancelled
            order.order_note = (order.order_note or '') + f"\nCancellation Reason: {reason}"  # Optionally store reason in notes
            order.save()
            messages.success(request, f'Order #{order.order_number} has been cancelled.')
        else:
            messages.warning(request, 'Order already cancelled.')
    return redirect('my_orders')
