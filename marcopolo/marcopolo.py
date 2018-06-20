import argparse
import configparser
import datetime
import logging
import multiprocessing as mp
import os
import sys
import time

from poloniex import Poloniex
from pymongo import MongoClient

from ticker import Ticker

parser = argparse.ArgumentParser()
parser.add_argument('-r', '--restticker', action='store_true', default=False, help='Use REST API for ticker data rather than MongoDB ticker.')
parser.add_argument('-l', '--live', action='store_true', default=False, help='Activate live trading mode.')
parser.add_argument('-d', '--dropdb', action='store_true', default=False, help='Drop MongoDB trade collection and start fresh.')
args = parser.parse_args()

rest_ticker = args.restticker
live_mode = args.live
drop_db = args.dropdb

mongo_ip = 'mongodb://192.168.1.179:27017/'

order_number_debug = 10000000000
trade_id_debug = 10000000
global_trade_id_debug = 100000000

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class MarcoPolo:
    def __init__(self, config_path, ws_ticker=True, debug_mode=False):
        config = configparser.ConfigParser()
        config.read(config_path)

        polo_api = config['poloniex']['api']
        polo_secret = config['poloniex']['secret']

        self.polo = Poloniex(polo_api, polo_secret)

        self.db = MongoClient(mongo_ip).marcopolo['trades']

        #if drop_db == True:
        self.db.drop()

        #self.ticker = MongoClient(mongo_ip).poloniex['ticker']
        self.ticker = Ticker(mongo_ip)

        self.ws_ticker = ws_ticker

        self.debug_mode = debug_mode


    def create_trade(self, market, buy_target, profit_level, stop_level, stop_price=None,
                     spend_proportion=0.01, price_tolerance=0.001, entry_timeout=5, taker_fee_ok=True):
        create_trade_successful = True

        try:
            self.market = market
            logger.debug('self.market: ' + self.market)

            self.base_currency = self.market.split('_')[0]
            logger.debug('self.base_currency: ' + self.base_currency)

            self.trade_currency = self.market.split('_')[1]
            logger.debug('self.trade_currency: ' + self.trade_currency)

            self.buy_target = buy_target
            logger.debug('self.buy_target: ' + str(self.buy_target))

            self.buy_max = round(self.buy_target * (1 + price_tolerance), 8)
            logger.debug('self.buy_max: ' + str(self.buy_max))

            self.spend_proportion = spend_proportion
            logger.debug('self.spend_proportion: ' + str(self.spend_proportion))

            if self.debug_mode == False:
                try:
                    balance_base_currency = self.polo.returnAvailableAccountBalances()['exchange'][self.base_currency]

                except:
                    logger.error(self.base_currency + ' balance currently 0. Unable to continue with trade. Exiting.')

                    create_trade_successful = False

                    sys.exit(1)

            else:
                balance_base_currency = 10

            logger.debug('balance_base_currency: ' + str(balance_base_currency))

            self.spend_amount = round(balance_base_currency * self.spend_proportion, 8)
            logger.debug('self.spend_amount: ' + str(self.spend_amount))

            #self.buy_amount_target = round(self.spend_amount * self.buy_target, 8)
            #logger.debug('self.buy_amount_target: ' + str(self.buy_amount_target))

            self.profit_level = profit_level
            logger.debug('self.profit_level: ' + str(self.profit_level))

            self.sell_price = round(self.buy_target * (1 + self.profit_level), 8)
            logger.debug('self.sell_price: ' + str(self.sell_price))

            self.stop_level = stop_level
            logger.debug('self.stop_level: ' + str(self.stop_level))

            if stop_price == None:
                self.stop_price = round(self.buy_target * (1 - self.stop_level), 8)
                logger.debug('self.stop_price: ' + str(self.stop_price))

            else:
                if stop_price < self.buy_target:
                    self.stop_price = stop_price

                else:
                    logger.error('Invalid parameters. Stop price set equal to or greater than buy target.')

                    create_trade_result = False

            self.price_tolerance = price_tolerance
            logger.debug('self.price_tolerance: ' + str(self.price_tolerance))

            self.abort_time = datetime.datetime.now() + datetime.timedelta(minutes=entry_timeout)
            logger.debug('self.abort_time: ' + str(self.abort_time))

            fee_info = self.polo.returnFeeInfo()

            self.maker_fee = fee_info['makerFee']
            logger.debug('self.maker_fee: ' + str(self.maker_fee))

            self.taker_fee = fee_info['takerFee']
            logger.debug('self.taker_fee: ' + str(self.taker_fee))

            self.taker_fee_ok = taker_fee_ok
            logger.debug('self.taker_fee_ok: ' + str(self.taker_fee_ok))

            trade_doc = dict(market=self.market, time=datetime.datetime.now(),
                             buy=dict(target=self.buy_target,
                                      max=self.buy_max,
                                      spend=self.spend_amount,
                                      spend_actual=None,
                                      amount_actual=None,
                                      price_actual=None,
                                      abort_time=self.abort_time,
                                      complete=False,
                                      orders=[]),
                             sell=dict(target=self.sell_price,
                                       amount=None,
                                       stop=self.stop_price,
                                       threshold=None,
                                       gain_actual=None,
                                       amount_actual=None,
                                       complete=False,
                                       result=None,
                                       order_number=None,
                                       stop_active=None,
                                       orders=[]),
                             fees=dict(maker=self.maker_fee, taker=self.taker_fee),
                             parameters=dict(market=market,
                                             buy_target=buy_target,
                                             profit_level=profit_level,
                                             stop_level=stop_level,
                                             stop_price=stop_price,
                                             spend_proportion=spend_proportion,
                                             price_tolerance=price_tolerance,
                                             entry_timeout=entry_timeout,
                                             taker_fee_ok=taker_fee_ok))

            logger.info('Creating MongoDB trade document.')

            try:
                self.db.update_one(
                    {'_id': self.market},
                    {'$set': trade_doc},
                    upsert=True
                )

            except Exception as e:
                logger.exception('Exception while creating MongoDB trade document.')
                logger.exception(e)

                create_trade_successful = False

        except Exception as e:
            logger.exception('Exception in create_trade().')
            logger.exception(e)

            create_trade_successful = False

        finally:
            return create_trade_successful


    def run_trade_cycle(self):
        def debug_triggers():
            global order_number_debug
            global global_trade_id_debug
            global trade_id_debug
            global order_trades_debug

            trade_doc = self.db.find_one({'_id': self.market})

            candle_current = polo.returnChartData(currencyPair=self.market, period=300, start=(datetime.datetime.now().timestamp() - 301))[-1]

            """
            "order_trades": [
                {
                    "amount": 5.0,
                    "currencyPair": "BTC_STR",
                    "date": "2018-06-20 01:07:29",
                    "fee": 0.002,
                    "globalTradeID": 123456789,
                    "rate": 3.451e-05,
                    "total": 0.00017255,
                    "tradeID": 12345678,
                    "type": "sell"
                }
            ]
            """

            if candle_current['high'] >= self.sell_price:
                global_trade_id_debug += 1
                trade_id_debug += 1

                order_trades_debug = []

                order = dict(amount=trade_doc['sell']['amount'],
                             currencyPair=self.market,
                             date=datetime.datetime.utcnow().isoformat(sep=' ', timespec='seconds'),
                             fee=self.maker_fee,
                             globalTradeID=global_trade_id_debug,
                             rate=trade_doc['sell']['target'],
                             total=round((trade_doc['sell']['amount'] * trade_doc['sell']['target']) * (1 - self.maker_fee), 8),
                             tradeID=trade_id_debug,
                             type='sell')

                order_trades_debug.append(order)


        def generate_debug_order(order_type, rate=None, amount=None, order_number=None):
            import random

            global order_number_debug
            global trade_id_debug

            order_return = {'success': True, 'result': {}}

            try:
                if order_type == 'buy':
                    if rate == None or amount == None:
                        logger.error('Must provide rate and amount for buy order.')

                        order_return['success'] = False

                    else:
                        order_number_debug += 1

                        rand_props = []
                        rand_props.append(round(random.uniform(0.1, 0.9), 8))
                        rand_props.append(1 - rand_props[0])

                        trade_id_debug_list = []
                        trade_total_debug_list = []

                        for x in range(0, 2):
                            trade_id_debug += 1
                            trade_id_debug_list.append(trade_id_debug)

                            trade_total_debug_list.append((round(amount * rand_props[x], 8), round((amount * rand_props[x]) * (1 - self.taker_fee), 8)))

                        dt_utc = datetime.datetime.utcnow()

                        dt_debug_list = [dt_utc.isoformat(sep=' ', timespec='seconds'), (dt_utc + datetime.timedelta(seconds=1)).isoformat(sep=' ', timespec='seconds')]

                        order_return['result'] = {
                            'orderNumber': order_number_debug,
                            'resultingTrades': [
                                {
                                    'amount': trade_total_debug_list[0][1],
                                    'date': dt_debug_list[0],
                                    'rate': rate,
                                    'total': (rate * trade_total_debug_list[0][0]),
                                    'tradeID': trade_id_debug_list[0],
                                    'type': 'buy'
                                },
                                {
                                    'amount': trade_total_debug_list[1][1],
                                    'date': dt_debug_list[1],
                                    'rate': rate,
                                    'total': (rate * trade_total_debug_list[1][0]),
                                    'tradeID': trade_id_debug_list[1],
                                    'type': 'buy'
                                }
                            ],
                            'amountUnfilled': 0.0
                        }

                elif order_type == 'sell':
                    if rate == None or amount == None:
                        logger.error('Must provide rate and amount for buy order.')

                        order_return['success'] = False

                    else:
                        order_number_debug += 1

                        order_return['result'] = {
                            'orderNumber': order_number_debug,
                            'resultingTrades': []
                        }

                        open_orders_debug.append(order_return['result'])

                elif order_type == 'cancel':
                    if order_number == None:
                        logger.error('Must provide order number to cancel order.')

                        order_return['success'] = False

                    else:
                        trade_doc = self.db.find_one({'_id': self.market})

                        cancel_message = 'Order #' + str(trade_doc['sell']['order']) + ' canceled.'

                        order_return['result'] = {
                            'success': int(1),
                            'amount': trade_doc['sell']['amount'],
                            'message': cancel_message
                        }

                        del_pos = -1

                        for x in range(0, len(open_orders_debug)):
                            if open_orders_debug[x]['orderNumber'] == trade_doc['sell']['order']:
                                del_pos = x

                                break

                        open_orders_debug.remove(open_orders_debug[del_pos])

                elif order_type == 'open_orders':
                    order_return['result'] = open_orders_debug

                elif order_type == 'order_trades':
                    order_return['result'] = order_trades_debug

            except Exception as e:
                logger.exception('Exception while generating debug results.')
                logger.exception(e)

                order_return['success'] = False

            finally:
                return order_return


        if self.debug_mode == True:
            polo_data_file_debug = '../resources/polo_data.json'

            # Load debug order and trade data
            with open(debug_polo_data_file, 'r', encoding='utf-8') as file:
                polo_data_debug = json.load(file)

                open_orders_debug = polo_data_debug['open_orders']

                order_trades_debug = {}

        ## Main Trade Cycle ##
        trade_cycle_success = True

        try:
            trade_doc = self.db.find_one({'_id': self.market})

            ## Entry buy ##
            entry_buy_complete = False

            spend_total = 0
            amount_total = 0

            while entry_buy_complete == False:
                try:
                    if self.taker_fee_ok == True:
                        # Place immediateOrCancel buy at lowest ask
                        # If spend amount filled, break
                        # If not, check if next lowest ask below max buy price
                        # If yes, place another immediateOrCancel buy at lowest ask
                        # Continue until spend amount fulfilled or timeout

                        if self.ws_ticker == True:
                            tick = self.ticker(self.market)
                        else:
                            tick = self.polo.returnTicker()[self.market]

                        lowest_ask = tick['lowestAsk']

                        logger.debug('lowest_ask: ' + str(lowest_ask) + ' / self.buy_max: ' + str(self.buy_max))

                        if lowest_ask <= self.buy_max:
                            buy_amount = round(lowest_ask * (trade_doc['buy']['spend'] - spend_total), 8)
                            logger.debug('buy_amount: ' + str(buy_amount))

                            if buy_amount <= 0:
                                logger.info('Buy amount satisfied.')

                                entry_buy_complete = True

                                break

                            if self.debug_mode == False:
                                result = polo.buy(currencyPair=self.market, rate=lowest_ask, amount=buy_amount, immediateOrCancel=1)
                            else:
                                # Simulate buy fulfilment
                                result = generate_debug_order(order_type='buy', rate=lowest_ask, amount=buy_amount)

                                if result['success'] == True:
                                    result = result['result']

                                else:
                                    logger.error('Failed to generate debug trade return. Exiting.')

                                    sys.exit(1)

                            logger.debug('result: ' + str(result))

                            if len(result['resultingTrades']) > 0:
                                trade_doc['buy']['orders'].append(result)

                                for trade in result['resultingTrades']:
                                    spend_total += trade['total']
                                    amount_total += trade['amount']

                                if result['amountUnfilled'] == 0:
                                    logger.info('Entry buy complete.')

                                    entry_buy_complete = True

                                else:
                                    logger.info('Partial buy filled. Continuing.')

                            else:
                                logger.info('Buy not executed at requested price. Recalculating and trying again.')

                    else:
                        # Create "BFB" order that follows price
                        pass

                    if datetime.datetime.now() >= self.abort_time:
                        logger.warning('Entry buy not completed before timeout reached.')

                        # If no buys executed
                        if spend_total == 0:
                            logger.warning('No buys executed. Removing trade document and exiting.')

                            delete_result = self.db.delete_one({'_id': self.market})
                            logger.debug('delete_result: ' + str(delete_result))

                            break

                        else:
                            entry_buy_complete = True

                            logger.warning('Continuing trade cycle with partial buy amount.')

                    time.sleep(0.2)     # To keep API calls to under 6 per second (very conservatively)

                except Exception as e:
                    logger.exception('Exception while placing entry buy.')
                    logger.exception(e)

            if entry_buy_complete == True:
                trade_doc['buy']['spend_actual'] = spend_total
                trade_doc['buy']['amount_actual'] = amount_total
                trade_doc['buy']['price_actual'] = round(spend_total / amount_total, 8)

                trade_doc['buy']['complete'] = True

                trade_doc['sell']['amount'] = amount_total

                update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc}, upsert=True)
                logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

            else:
                # Delete the trade doc and exit
                logger.warning('Could not complete any portion of entry buy. Exiting.')

                sys.exit()

            trade_doc = self.db.find_one({'_id': self.market})

            while (True):
                try:
                    ## Place sell order ##
                    if self.debug_mode == False:
                        result = polo.sell(currencyPair=self.market, rate=self.sell_price, amount=trade_doc['sell']['amount'])
                    else:
                        # Simulate sell fulfilment
                        result = generate_debug_order(order_type='sell', rate=self.sell_price, amount=trade_doc['sell']['amount'])

                        if result['success'] == True:
                            result = result['result']

                        else:
                            logger.error('Failed to generate debug trade return. Exiting.')

                            sys.exit(1)

                    logger.debug('result: ' + str(result))

                    trade_doc['sell']['order'] = result['orderNumber']

                    trade_doc['sell']['orders'].append(result)

                    update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                    logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                    logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                    break

                except Exception as e:
                    logger.exception(e)

                    logger.warning('Failed to place sell order. Retrying in 30 seconds.')

                    time.sleep(30)

            logger.info('Sell order placed at ' + str(self.sell_price) + ' ' + self.base_currency + '.')

            ## Monitor conditions in real-time

            stop_active = False

            trade_doc['sell']['stop_active'] = stop_active

            if trade_doc['buy']['price_actual'] < self.buy_target:
                baseline = trade_doc['buy']['price_actual']

            else:
                baseline = self.buy_target

            self.threshold = round(baseline - ((baseline - self.stop_price) * self.price_tolerance), 8)

            trade_doc['sell']['threshold'] = self.threshold
            logger.debug('trade_doc[\'sell\'][\'threshold\']: ' + str(trade_doc['sell']['threshold']))

            update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
            logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
            logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

            logger.info('Beginning price monitoring.')

            while (True):
                try:
                    ## Monitor price/sell order status and execute stop-loss if necessary ##

                    # If market price above (buy_target * (1 - price_tolerance)), set limit sell
                    # If market price below (buy_target * (1 - price_tolerance)), remove limit sell and monitor for stop-loss execution trigger

                    # Limit sell currently on book
                    if stop_active == False:
                        if self.ws_ticker == True:
                            tick = self.ticker(self.market)
                        else:
                            tick = self.polo.returnTicker()[self.market]

                        highest_bid = tick['highestBid']

                        logger.debug('highest_bid: ' + str(highest_bid) + ' / self.threshold: ' + str(self.threshold))

                        if highest_bid < self.threshold:
                            logger.info('Highest bid below stop-loss monitoring threshold. Canceling current sell order.')

                            while (True):
                                # Remove sell order
                                if self.debug_mode == False:
                                    cancel_result = polo.cancelOrder(trade_doc['sell']['order'])
                                else:
                                    # Simulate successful cancel
                                    cancel_result = generate_debug_order(order_type='cancel', order_number=trade_doc['sell']['order'])

                                    if cancel_result['success'] == True:
                                        cancel_result = cancel_result['result']

                                    else:
                                        logger.error('Failed to generate debug trade return. Exiting.')

                                        sys.exit(1)

                                logger.debug('cancel_result: ' + str(cancel_result))

                                if cancel_result['success'] == 1:
                                    logger.info(cancel_result['message'])

                                    trade_doc['sell']['orders'].append(cancel_result)

                                    logger.info('Sell order cancelled successfully.')

                                    ##
                                    # Now there's no order on books, so manual stop order can be executed with full buy amount.
                                    ##

                                    logger.info('Setting stop-loss monitor to active.')

                                    stop_active = True

                                    trade_doc['sell']['stop_active'] = True

                                    update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                    logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                    logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                                    break

                                else:
                                    logger.error('Failed to cancel order.')

                                    if 'message' in cancel_result:
                                        logger.info('cancel_result[\'message\']: ' + cancel_result['message'])

                        else:
                            if self.debug_mode == False:
                                open_orders = polo.returnOpenOrders(currencyPair=self.market)
                            else:
                                #open_orders = trade_doc['sell']['orders']
                                open_orders = generate_debug_order(order_type='open_orders')

                            for order in open_orders:
                                if order['orderNumber'] == trade_doc['sell']['order']:
                                    break

                            else:
                                logger.info('Sell order not found in open orders. Checking order info.')

                                if self.debug_mode == False:
                                    order_trades = polo.returnOrderTrades(trade_doc['sell']['order'])
                                else:
                                    order_trades = generate_debug_order(order_type='order_trades')

                                if len(order_trades) > 0:
                                    # Calculate actuals
                                    # Make sure amount bought = amount sold
                                    # Log to db
                                    # Archive trade doc?
                                    order_trades_dict = {'order_trades': order_trades}

                                    trade_doc['sell']['orders'].append(order_trades_dict)

                                    amount_total = 0
                                    gain_total = 0

                                    for trade in order_trades:
                                        amount_total += trade['amount']
                                        gain_total += trade['total']

                                    trade_doc['sell']['amount_actual'] = amount_total
                                    trade_doc['sell']['gain_actual'] = gain_total

                                    trade_doc['sell']['complete'] = True
                                    trade_doc['sell']['result'] = 'target'

                                    update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                    logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                    logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                                    if trade_doc['sell']['amount_actual'] != trade_doc['sell']['amount']:
                                        # Warning about incomplete sell order
                                        pass

                                    logger.info('Target sell order complete.')

                                    break

                                else:
                                    logger.error('No open sell orders or sell order trades found. An error has occurred. Exiting.')

                                    sys.exit(1)

                    ## Stop-loss monitoring active
                    else:
                        logger.debug('highest_bid: ' + str(highest_bid) + ' / self.threshold: ' + str(self.threshold))

                        logger.info('Starting stop-loss trigger monitor.')

                        while (True):
                            # Monitor for stop-loss condition and execute if necessary
                            if self.ws_ticker == True:
                                tick = self.ticker(self.market)
                            else:
                                tick = polo.returnTicker()[self.market]

                            highest_bid = tick['highestBid']

                            if highest_bid > self.threshold:
                                while (True):
                                    try:
                                        ## Place sell order ##
                                        if self.debug_mode == False:
                                            result = polo.sell(currencyPair=self.market, rate=self.sell_price, amount=trade_doc['sell']['amount'])
                                        else:
                                            # Simulate sell fulfilment
                                            result = generate_debug_order(order_type='sell', rate=self.sell_price, amount=trade_doc['sell']['amount'])

                                            if result['success'] == True:
                                                result = result['result']

                                            else:
                                                logger.error('Failed to generate debug trade return. Exiting.')

                                                sys.exit(1)

                                        logger.debug('result: ' + str(result))

                                        trade_doc['sell']['order'] = result['orderNumber']

                                        update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                        logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                        logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                                        break

                                    except Exception as e:
                                        logger.exception(e)

                                        logger.warning('Failed to place sell order. Retrying.')

                                        time.sleep(5)

                                logger.info('Sell order placed at ' + str(self.sell_price) + ' ' + self.base_currency + '.')

                                logger.info('Setting stop-loss monitor to inactive.')

                                stop_active = False

                                trade_doc['sell']['stop_active'] = False

                                update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                            elif highest_bid <= (self.stop_price * (1 + self.price_tolerance)):
                                # Begin orderbook checks for stop-loss triggering
                                if self.ws_ticker == True:
                                    tick = self.ticker(self.market)
                                else:
                                    tick = polo.returnTicker()[self.market]

                                highest_bid = tick['highestBid']
                                logger.debug('highest_bid: ' + str(highest_bid))

                                while highest_bid <= (self.stop_price * (1 + self.price_tolerance)):
                                    ob = polo.returnOrderBook(currencyPair=self.market)

                                    amount_total = 0
                                    for bid in ob['bids']:
                                        amount_total += float(bid[1])

                                        if amount_total >= trade_doc['sell']['amount']:
                                            if float(bid[0]) <= self.stop_price:
                                                # Execute stop-loss order
                                                sell_price = self.stop_price

                                                sold_total = 0

                                                while (True):
                                                    if self.ws_ticker == True:
                                                        tick = ticker(self.market)
                                                    else:
                                                        tick = self.polo.returnTicker()[self.market]

                                                    highest_bid = tick['highestBid']
                                                    logger.debug('highest_bid: ' + str(highest_bid))

                                                    if highest_bid < sell_price:
                                                        sell_price = highest_bid

                                                    sell_amount = trade_doc['sell']['amount'] - sold_total

                                                    if self.debug_mode == False:
                                                        result = polo.sell(currencyPair=self.market, rate=sell_price, amount=sell_amount, immedateOrCancel=1)
                                                    else:
                                                        # Simulate sell fulfilment
                                                        result = generate_debug_order(order_type='sell', rate=sell_price, amount=sell_amount)

                                                        if result['success'] == True:
                                                            result = result['result']

                                                        else:
                                                            logger.error('Failed to generate debug trade return. Exiting.')

                                                            sys.exit(1)

                                                    logger.debug('result: ' + str(result))

                                                    if len(result['resultingTrades']) > 0:
                                                        trade_doc['sell']['orders'].append(result)

                                                        for trade in result['resultingTrades']:
                                                            sold_total += trade['amount']

                                                        if result['amountUnfilled'] == 0:
                                                            logger.info('Stop-loss order executed successfully.')

                                                            trade_doc['sell']['complete'] = True
                                                            trade_doc['sell']['result'] = 'stop'

                                                            break

                                                        else:
                                                            logger.info('Sell partially filled. Continuing.')

                                                    else:
                                                        logger.info('Sell not executed at requested price. Recalculating and trying again.')

                                    time.sleep(0.2)

                    #time.sleep(0.2)
                    time.sleep(5)

                except Exception as e:
                    logger.exception('Exception while monitoring sell conditions.')
                    logger.exception(e)

            logger.info('Exiting trade cycle.')

        except Exception as e:
            logger.exception('Exception in run_trade_cycle().')
            logger.exception(e)

            trade_cycle_success = False

        finally:
            return trade_cycle_success


if __name__ == '__main__':
    #import multiprocessing as mp

    try:
        polo = Poloniex()

        test_config_path = '../config/config.ini'

        if rest_ticker == True:
            ws_ticker_switch = False
        else:
            ws_ticker_switch = True

        if live_mode == True:
            debug_switch = False
        else:
            debug_switch = True

        ################
        ws_ticker_switch = False
        ################

        marcopolo = MarcoPolo(config_path=test_config_path, ws_ticker=ws_ticker_switch, debug_mode=debug_switch)

        test_market = 'BTC_STR'
        logger.debug('test_market: ' + test_market)
        test_buy_target = polo.returnTicker()['BTC_STR']['last']
        logger.debug('test_buy_target: ' + str(test_buy_target))
        test_profit_level = 0.015
        logger.debug('test_profit_level: ' + str(test_profit_level))
        test_stop_level = 0.01
        logger.debug('test_stop_level: ' + str(test_stop_level))
        test_spend_proportion = 0.01
        logger.debug('test_spend_proportion: ' + str(test_spend_proportion))
        test_entry_timeout = 5
        logger.debug('test_entry_timeout: ' + str(test_entry_timeout))

        create_trade_result = marcopolo.create_trade(market=test_market, buy_target=test_buy_target,
                                                     profit_level=test_profit_level, stop_level=test_stop_level,
                                                     spend_proportion=test_spend_proportion, entry_timeout=test_entry_timeout,
                                                     price_tolerance=0.0025)

        logger.debug('create_trade_result: ' + str(create_trade_result))

        if create_trade_result == True:
            logger.info('Starting trade cycle.')

            trade_cycle_result = marcopolo.run_trade_cycle()

            logger.info('Trade Cycle Result: ' + str(trade_cycle_result))

            """
            arguments = tuple()

            #keyword_arguments = {}

            trade_proc = mp.Process(target=marcopolo.run_trade_cycle)#, args=arguments)#, kwargs=keyword_arguments)

            logger.info('Starting trade cycle process.')

            trade_proc.start()

            logger.info('Joining trade cycle process.')

            trade_proc.join()
            """

            logger.info('Done.')

    except Exception as e:
        logger.exception('Uncaught exception in __main__.')
        logger.exception(e)

    except KeyboardInterrupt:
        logger.info('Exit signal received.')

        logger.info('Attempting to stop trade cycle process.')

        try:
            trade_proc.stop()

        except:
            logger.warning('Could not stop trade cycle process. It may not have been started.')

    finally:
        ################
        delete_result = marcopolo.db.delete_one({'_id': marcopolo.market})
        #logger.debug('delete_result.matched_count: ' + str(delete_result.matched_count))
        #logger.debug('delete_result.modified_count: ' + str(delete_result.modified_count))
        logger.debug('delete_result.deleted_count: ' + str(delete_result.deleted_count))
        ################

        logger.info('Exiting.')
