# SPDX-License-Identifier: GPL-3.0-or-later
def classFactory(iface):
    from .plugin import SuperResolutionPlugin
    return SuperResolutionPlugin(iface)

