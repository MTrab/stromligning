![Current Release](https://img.shields.io/github/release/mtrab/stromligning/all.svg?style=plastic)
![Github All Releases](https://img.shields.io/github/downloads/mtrab/stromligning/total.svg?style=plastic)
<!--![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=plastic)-->

<a href="https://www.buymeacoffee.com/mtrab" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

Stromligning for Home Assistant integrates Day Ahead spotprices for electricity, from the Stromligning API.

The integration automatically recognises tariff settings from the Home Assistant home location coordinates and allows you to select your electricity vendor.

## Table of Content

[**Installation**](#installation)

[**Setup**](#setup)
 

## Installation:

### ~~Option 1 (easy) - HACS:~~

*   ~~Ensure that HACS is installed.~~
*   ~~Search for and install the "Stromligning" integration.~~
*   ~~Restart Home Assistant.~~

### Option 2 - Manual installation:

*   Download the latest release.
*   Unpack the release and copy the custom\_components/stromligning directory into the custom\_components directory of your Home Assistant installation.
*   Restart Home Assistant.

## Setup

My Home Assistant shortcut:

[![](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=stromligning)

Or go to Home Assistant > Settings > Integrations

Add "Stromligning" integration _(If it doesn't show, try CTRL+F5 to force a refresh of the page)_
