from __future__ import print_function

from .core import AutoFallback, enforce_service_mode
from .historical_price import Quandl
from .crypto_data import crypto_data
from bitcoin import sha256, pubtoaddr, privtopub, encode_privkey, encode_pubkey
from .bip38 import bip38_encrypt

def get_optimal_services(crypto, type_of_service):
    try:
        # get best services from curated list
        return crypto_data[crypto.lower()]['services'][type_of_service]
    except KeyError:
        raise ValueError("Invalid cryptocurrency symbol: %s" % crypto)


def get_magic_bytes(crypto):
    try:
        return (
            crypto_data[crypto]['address_version_byte'],
            crypto_data[crypto]['private_key_prefix']
        )

    except KeyError:
        raise ValueError("Invalid cryptocurrency symbol: %s" % crypto)


def get_current_price(crypto, fiat, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'current_price')

    return enforce_service_mode(
        services, CurrentPrice, {'crypto': crypto, 'fiat': fiat}, modes=modes
    )


def get_address_balance(crypto, address=None, addresses=None, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'address_balance')

    args = {'crypto': crypto}

    if address:
        args['address'] = address
    elif addresses:
        args['addresses'] = addresses
    else:
        raise Exception("Either address or addresses but not both")

    return enforce_service_mode(
        services, AddressBalance, args, modes=modes
    )


def get_historical_transactions(crypto, address, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'historical_transactions')

    return enforce_service_mode(
        services, HistoricalTransactions, {'crypto': crypto, 'address': address}, modes=modes
    )


def get_unspent_outputs(crypto, address, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'unspent_outputs')
    return enforce_service_mode(
        services, UnspentOutputs, {'crypto': crypto, 'address': address}, modes=modes
    )


def get_historical_price(crypto, fiat, date):
    """
    Only one service is defined fr geting historical price, so no fetching modes
    are needed.
    """
    return HistoricalPrice().get(crypto, fiat, date)


def push_tx(crypto, tx_hex, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'push_tx')
    return enforce_service_mode(
        services, PushTx, {'crypto': crypto, 'tx_hex': tx_hex}, modes=modes
    )


def get_block(crypto, block_number='', block_hash='', latest=False, services=None, **modes):
    if not services:
        services = get_optimal_services(crypto, 'get_block')
    kwargs = dict(crypto=crypto, block_number=block_number, block_hash=block_hash, latest=latest)
    return enforce_service_mode(
        services, GetBlock, kwargs, modes=modes
    )


def get_optimal_fee(crypto, tx_bytes, acceptable_block_delay, verbose=False):
    """
    Get the optimal fee based on how big the transaction is. Currently this
    isonly providerfor BTC. Other currencies will return $0.02 in satoshi.
    """
    if crypto == 'btc':
        services = get_optimal_services(crypto, 'get_optimal_fee')
        of = OptimalFee(services=services, verbose=verbose)
        return of.action(crypto, tx_bytes, acceptable_block_delay)
    else:
        convert = get_current_price(crypto, 'usd')[0]
        return int(0.02 / convert * 1e8)


def generate_keypair(crypto, seed, password=None):
    """
    Generate a private key and publickey for any currency, given a seed.
    That seed can be random, or a brainwallet phrase.
    """
    pub_byte, priv_byte = get_magic_bytes(crypto)
    priv = sha256(seed)
    pub = privtopub(priv)

    if priv_byte >= 128:
        priv_byte -= 128 #pybitcointools bug

    priv_wif = encode_privkey(priv, 'wif_compressed', vbyte=priv_byte)
    if password:
        priv_wif = bip38_encrypt(priv_wif, password)

    #from ipdb import set_trace; set_trace()

    compressed_pub = encode_pubkey(pub, 'hex_compressed')
    ret = {
        'public': {
            'hex_uncompressed': pub,
            'hex': compressed_pub,
            'address': pubtoaddr(compressed_pub, pub_byte)
        },
        'private': {
            'wif': priv_wif
        }
    }
    if not password:
        # only these are valid when no bip38 password is supplied
        ret['private']['hex'] = encode_privkey(priv, 'hex_compressed', vbyte=priv_byte)
        ret['private']['hex_uncompressed'] = encode_privkey(priv, 'hex', vbyte=priv_byte)
        ret['private']['wif_uncompressed'] = encode_privkey(priv, 'wif', vbyte=priv_byte)

    return ret

def sweep(crypto, private_key, to_address, fee=None, password=None, **modes):
    """
    Move all funds by private key to another address.
    """
    from moneywagon.tx import Transaction
    tx = Transaction(crypto, verbose=modes.get('verbose', False))
    tx.add_inputs(private_key=private_key, password=password, **modes)
    tx.change_address = to_address
    tx.fee(fee)

    return tx.push()


class OptimalFee(AutoFallback):
    def action(self, crypto, tx_bytes, acceptable_block_delay=0):
        crypto = crypto.lower()
        return self._try_services("get_optimal_fee", crypto, tx_bytes, acceptable_block_delay)

    def no_service_msg(self, crypto, tx_bytes, acceptable_block_delay):
        return "Could not get optimal fee for: %s" % crypto


class GetBlock(AutoFallback):
    def action(self, crypto, block_number='', block_hash='', latest=False):
        if sum([bool(block_number), bool(block_hash), bool(latest)]) != 1:
            raise ValueError("Only one of `block_hash`, `latest`, or `block_number` allowed.")
        return self._try_services(
            'get_block', crypto, block_number=block_number, block_hash=block_hash, latest=latest
        )

    def no_service_msg(self, crypto, block_number='', block_hash='', latest=False):
        return "Could not get %s block: %s%s%s" % (
            crypto, block_number, block_hash, 'latest' if latest else ''
        )

    @classmethod
    def strip_for_consensus(self, results):
        stripped = []
        for result in results:
            stripped.append(
                "[hash: %s, number: %s, size: %s]" % (
                    result['hash'], result['block_number'], result['size']
                )
            )
        return stripped


class HistoricalTransactions(AutoFallback):
    def action(self, crypto, address):
        return self._try_services('get_transactions', crypto, address)

    def no_service_msg(self, crypto, address):
        return "Could not get transactions for: %s" % crypto

    @classmethod
    def strip_for_consensus(cls, results):
        stripped = []
        for result in results:
            result.sort(key=lambda x: x['date'])
            stripped.append(
                ", ".join(
                    ["[id: %s, amount: %s]" % (x['txid'], x['amount']) for x in result]
                )
            )
        return stripped


class UnspentOutputs(AutoFallback):
    def action(self, crypto, address):
        return self._try_services('get_unspent_outputs', crypto=crypto, address=address)

    def no_service_msg(self, crypto, address):
        return "Could not get unspent outputs for: %s" % crypto

    @classmethod
    def strip_for_consensus(cls, results):
        stripped = []
        for result in results:
            result.sort(key=lambda x: x['output'])
            stripped.append(
                ", ".join(
                    ["[output: %s, value: %s]" % (x['output'], x['amount']) for x in result]
                )
            )
        return stripped


class CurrentPrice(AutoFallback):
    def action(self, crypto, fiat):
        if crypto.lower() == fiat.lower():
            return (1.0, 'math')

        return self._try_services('get_current_price', crypto=crypto, fiat=fiat)

    def simplify_for_average(self, value):
        return value[0] # ignore source tag for average calculation

    def no_service_msg(self, crypto, fiat):
        return "Can not find current price for %s->%s" % (crypto, fiat)


class AddressBalance(AutoFallback):
    def action(self, crypto, address=None, addresses=None, confirmations=1):
        kwargs = dict(crypto=crypto, confirmations=confirmations)

        if address:
            method_name = "get_balance"
            kwargs['address'] = address

        if addresses:
            method_name = "get_balance_multi"
            kwargs['addresses'] = addresses

        return self._try_services(method_name, **kwargs)

    def no_service_msg(self, crypto, address, confirmations=1):
        return "Could not get confirmed address balance for: %s" % crypto


class PushTx(AutoFallback):
    def action(self, crypto, tx_hex):
        return self._try_services("push_tx", crypto=crypto, tx_hex=tx_hex)

    def no_service_msg(self, crypto, tx_hex):
        return "Could not push this %s transaction." % crypto


class HistoricalPrice(object):
    """
    This one doesn't inherit from AutoFallback because there is only one
    historical price API service at the moment.
    """
    def __init__(self, responses=None, verbose=False):
        self.service = Quandl(responses, verbose=verbose)

    def action(self, crypto, fiat, at_time):
        crypto = crypto.lower()
        fiat = fiat.lower()

        if crypto != 'btc' and fiat != 'btc':
            # two external requests and some math is going to be needed.
            from_btc, source1, date1 = self.service.get_historical(crypto, 'btc', at_time)
            to_altcoin, source2, date2 = self.service.get_historical('btc', fiat, at_time)
            return (from_btc * to_altcoin), "%s x %s" % (source1, source2), date1
        else:
            return self.service.get_historical(crypto, fiat, at_time)

    @property
    def responses(self):
        return self.service.responses


def _get_all_services():
    """
    Go through the crypto_data structure and return all list of all (unique)
    installed services.
    """
    services = []
    for currency, data in crypto_data.items():
        if hasattr(data, 'append'):
            continue
        if 'services' not in data:
            continue

        services.append([
            item for sublist in data['services'].values() for item in sublist
        ])

    return set([item for sublist in services for item in sublist])


ALL_SERVICES = _get_all_services()
