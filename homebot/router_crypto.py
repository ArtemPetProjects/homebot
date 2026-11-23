# PURPOSE: AES-128 CBC для API роутера без внешних библиотек.
import base64

KEY = b"jiuzhou99jiuzhou"

SBOX = []
INV_SBOX = [0] * 256


def _gf_mul(a: int, b: int) -> int:
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        high = a & 0x80
        a = (a << 1) & 0xFF
        if high:
            a ^= 0x1B
        b >>= 1
    return result


def _gf_inv(a: int) -> int:
    if a == 0:
        return 0
    result = 1
    base = a
    exponent = 254
    while exponent:
        if exponent & 1:
            result = _gf_mul(result, base)
        base = _gf_mul(base, base)
        exponent >>= 1
    return result


def _build_sboxes() -> None:
    for value in range(256):
        inverse = _gf_inv(value)
        s = inverse
        for shift in (1, 2, 3, 4):
            rotated = ((inverse << shift) | (inverse >> (8 - shift))) & 0xFF
            s ^= rotated
        s ^= 0x63
        SBOX.append(s)
        INV_SBOX[s] = value


_build_sboxes()


def _key_expansion(key: bytes) -> list[list[int]]:
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for _ in range(40):
        temp = words[-1][:]
        if len(words) % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[byte] for byte in temp]
            temp[0] ^= rcon
            rcon = _gf_mul(rcon, 2)
        words.append([a ^ b for a, b in zip(words[-4], temp)])
    return [word for word in words]


def _add_round_key(state: list[int], round_keys: list[list[int]], round_number: int) -> None:
    for index in range(16):
        state[index] ^= round_keys[round_number * 4 + index // 4][index % 4]


def _shift_rows(state: list[int]) -> None:
    # Состояние хранится по столбцам: index = column * 4 + row.
    for row in (1, 2, 3):
        values = [state[column * 4 + row] for column in range(4)]
        shifted = values[row:] + values[:row]
        for column in range(4):
            state[column * 4 + row] = shifted[column]


def _inv_shift_rows(state: list[int]) -> None:
    for row in (1, 2, 3):
        values = [state[column * 4 + row] for column in range(4)]
        shifted = values[-row:] + values[:-row]
        for column in range(4):
            state[column * 4 + row] = shifted[column]


def _mix_columns(state: list[int]) -> None:
    for column in range(4):
        offset = column * 4
        a, b, c, d = state[offset:offset + 4]
        state[offset] = _gf_mul(a, 2) ^ _gf_mul(b, 3) ^ c ^ d
        state[offset + 1] = a ^ _gf_mul(b, 2) ^ _gf_mul(c, 3) ^ d
        state[offset + 2] = a ^ b ^ _gf_mul(c, 2) ^ _gf_mul(d, 3)
        state[offset + 3] = _gf_mul(a, 3) ^ b ^ c ^ _gf_mul(d, 2)


def _inv_mix_columns(state: list[int]) -> None:
    for column in range(4):
        offset = column * 4
        a, b, c, d = state[offset:offset + 4]
        state[offset] = _gf_mul(a, 14) ^ _gf_mul(b, 11) ^ _gf_mul(c, 13) ^ _gf_mul(d, 9)
        state[offset + 1] = _gf_mul(a, 9) ^ _gf_mul(b, 14) ^ _gf_mul(c, 11) ^ _gf_mul(d, 13)
        state[offset + 2] = _gf_mul(a, 13) ^ _gf_mul(b, 9) ^ _gf_mul(c, 14) ^ _gf_mul(d, 11)
        state[offset + 3] = _gf_mul(a, 11) ^ _gf_mul(b, 13) ^ _gf_mul(c, 9) ^ _gf_mul(d, 14)


def encrypt_block(block: bytes, key: bytes) -> bytes:
    keys = _key_expansion(key)
    state = list(block)
    _add_round_key(state, keys, 0)
    for round_number in range(1, 10):
        state = [SBOX[byte] for byte in state]
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, keys, round_number)
    state = [SBOX[byte] for byte in state]
    _shift_rows(state)
    _add_round_key(state, keys, 10)
    return bytes(state)


def decrypt_block(block: bytes, key: bytes) -> bytes:
    keys = _key_expansion(key)
    state = list(block)
    _add_round_key(state, keys, 10)
    for round_number in range(9, 0, -1):
        _inv_shift_rows(state)
        state = [INV_SBOX[byte] for byte in state]
        _add_round_key(state, keys, round_number)
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    state = [INV_SBOX[byte] for byte in state]
    _add_round_key(state, keys, 0)
    return bytes(state)


def _pad(data: bytes) -> bytes:
    length = 16 - (len(data) % 16)
    return data + bytes([length]) * length


def _unpad(data: bytes) -> bytes:
    length = data[-1]
    return data[:-length]


def aes_cbc_encrypt(text: str, key: bytes, iv: bytes) -> str:
    previous = iv
    blocks = []
    for offset in range(0, len(_pad(text.encode("utf-8"))), 16):
        chunk = _pad(text.encode("utf-8"))[offset:offset + 16]
        mixed = bytes(a ^ b for a, b in zip(chunk, previous))
        previous = encrypt_block(mixed, key)
        blocks.append(previous)
    return base64.b64encode(b"".join(blocks)).decode("ascii")


def aes_cbc_decrypt(payload: str, key: bytes, iv: bytes) -> str:
    data = base64.b64decode(payload)
    previous = iv
    plain = bytearray()
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        decrypted = decrypt_block(chunk, key)
        plain.extend(bytes(a ^ b for a, b in zip(decrypted, previous)))
        previous = chunk
    return _unpad(bytes(plain)).decode("utf-8")
