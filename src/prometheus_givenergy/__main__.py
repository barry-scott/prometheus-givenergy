#!/usr/bin/env python3
import sys
import prometheus_givenergy


def main( argv ):
    arg_iter = iter(argv)

    progname = next(arg_iter)

    opt_host = None
    opt_port = prometheus_givenergy.DEFAULT_PORT
    opt_debug = False
    opt_help = False
    opt_prom_file = prometheus_givenergy.DEFAULT_PROM_FILE

    name_opt_help = '--help'
    name_opt_version = '--version'
    name_opt_port = '--port='
    name_opt_prom_file = '--prom-file='
    name_opt_debug = '--debug'

    for arg in arg_iter:
        if arg.startswith('--'):
            if name_opt_version == arg:
                print('prometheus_givenergy', prometheus_givenergy.VERSION)
                return 0

            elif name_opt_help == arg:
                opt_help = True

            elif arg.startswith(name_opt_port):
                opt_port = int(arg[len(name_opt_port):])

            elif arg.startswith(name_opt_prom_file) and arg != name_opt_prom_file:
                opt_prom_file = arg[len(name_opt_prom_file):]

            elif name_opt_debug == arg:
                opt_debug = True

            else:
                print(f'Unknown option {arg!r}', file=sys.stderr)
                return 1

        else:
            opt_host = arg

    if opt_help or opt_host is None:
        print(f'Usage: {progname} <host> [{name_opt_port}<port>] [{name_opt_prom_file}<prom-file> [{name_opt_version}]')
        print(f'    <host> ip-address or hostname')
        print(f'    <port> default {prometheus_givenergy.DEFAULT_PORT}')
        print(f'    <prom-file> default {prometheus_givenergy.DEFAULT_PROM_FILE}')
        return 1

    prom = prometheus_givenergy.PrometheusGivEnergy(opt_host, port=opt_port, prom_file=opt_prom_file, debug=opt_debug)
    prom.report()

    return 0

if __name__ == '__main__':
    sys.exit( main( sys.argv ) )
