# -*- coding: utf-8 -*-
def classFactory(iface):
    from .wgs_coordconverter import WGSCoordConverterPlugin
    return WGSCoordConverterPlugin(iface)
