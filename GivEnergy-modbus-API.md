# GivEnergy-modbus-API

This analysis of the GivEnergy modbus API is taken from Dewet Diener's
<https://github.com/dewet22/givenergy-modbus/blob/main/givenergy_modbus/framer.py>

A framer abstracts away all the detail about how marshall the wire
protocol, e.g. to detect if a current message frame exists, decoding
it, sending it, etc.  This implementation understands the
idiosyncrasies of GivEnergy's implementation of the Modbus spec.

**Note that
the understanding below comes from observing the wire format and analysing the
data interchanges – no GivEnergy proprietary knowledge was needed or referred to.**

Packet exchange looks very similar to normal Modbus TCP on the wire, with each
message still having a regular 7-byte MBAP header consisting of:

  * `tid`, the transaction id
  * `pid`, the protocol id
  * `len`, the byte count / length of the remaining data following the header
  * `uid`, the unit id for addressing devices on the Modbus network

This is followed by `fid` / a function code to specify how the message should be
decoded into a PDU:

```
[_________MBAP Header______] [_fid_] [_______________data________________]
[_tid_][_pid_][_len_][_uid_]
  2b     2b     2b     1b      1b                  (len-1)b
```

GivEnergy's implementation quicks can be summarised as:

  * `tid` is always `0x5959/'YY'`, so the assumption/interpretation is that clients
     have to poll continually instead of maintaining long-lived connections and
     using varying `tid`s to pair requests with responses
  * `pid` is always `0x0001`, whereas normal Modbus uses `0x0000`
  * `len` **adds** 1 extra byte (anecdotally for the unit id?) which normal
     Modbus does not. This leads to continual off-by-one differences appearing
     whenever header/frame length calculations are done. This is probably the
     biggest reason Modbus libraries struggle working out of the box.
  * `unit_id` is always `0x01`
  * `fid` is always `0x02/Read Discrete Inputs` even for requests that modify
     registers. The actual intended function is encoded 19 bytes into the data
     block. You can interpret this as functionally somewhat akin to Modbus
     sub-functions where we always use the `0x02` main function.

Because these fields are static and we have to reinterpret what `len` means it is
simpler to just reconsider the entire header:

```
[___"MBAP+" Header____] [_______________GivEnergy Frame_______________]
[___h1___][_len_][_h2_]
    4b      2b     2b                      (len+2)b
```

  * `h1` is always `0x59590001`, so can be used as a sanity check during decoding
  * `len` needs 2 added during calculations because of the previous extra byte
     off-by-one inconsistency, plus expanding the header by including 1-byte `fid`
  * `h2` is always `0x0102`, so can be used as a sanity check during decoding

TODO These constant headers being present would allow for us to scan through the
bytestream to try and recover from stream errors and help reset the framing.

The GivEnergy frame itself has a consistent format:

```
[____serial____] [___pad___] [_addr_] [_func_] [______data______] [_crc_]
      10b            8b         1b       1b            Nb           2b
```

 * `serial` of the responding data adapter (wifi/GPRS?/ethernet?) plugged into
    the inverter. For requests this is simply hardcoded as a dummy `AB1234G567`
 * `pad`'s function is unknown - it appears to be a single zero-padded byte that
    varies across responses, so might be some kind of check/crc?
 * `addr` is the "slave" address, conventionally `0x32`
 * `func` is the actual function to be executed:
    * `0x3` - read holding registers
    * `0x4` - read input registers
    * `0x6` - write single register
 * `data` is specific to the invoked function
 * `crc` - for requests it is calculated using the function id, base register and
    step count, but it is not clear how those for responses are calculated (or
    should be checked)

In short, the message unframing algorithm is simply:

```python
while len(buffer) > 8:
  tid, pid, len, uid, fid = struct.unpack(">HHHBB", buffer)
  data = buffer[8:6+len]
  process_message(tid, pid, len, uid, fid, data)
  buffer = buffer[6+len:]  # skip buffer over frame
```
