![Current Release](https://img.shields.io/github/release/mtrab/stromligning/all.svg?style=plastic)
![Github All Releases](https://img.shields.io/github/downloads/mtrab/stromligning/total.svg?style=plastic)
![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=plastic)


<a href="https://www.buymeacoffee.com/mtrab" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

Stromligning for Home Assistant integrates Day Ahead spotprices for electricity, from the Stromligning API.

The integration automatically recognises tariff settings from the Home Assistant home location coordinates and allows you to select your electricity vendor.

## Table of Content

[**Installation**](#installation)

[**Setup**](#setup)

[**Use the custom template to show the next x cheapest hours**](#use-the-custom-template-to-show-the-next-x-cheapest-hours)
 

## Installation:

### Option 1 (easy) - HACS:

*   Ensure that HACS is installed.
*   Search for and install the "Stromligning" integration.
*   Restart Home Assistant.

### Option 2 - Add custom repository to HACS:

*   See [this link](https://www.hacs.xyz/docs/faq/custom_repositories/) for how to add a custom repository to HACS.
*   Add `https://github.com/MTrab/stromligning` as custom repository of type Integration
*   Search for and install the "Stromligning" integration.
*   Restart Home Assistant.

### Option 3 - Manual installation:

*   Download the latest release.
*   Unpack the release and copy the custom\_components/stromligning directory into the custom\_components directory of your Home Assistant installation.
*   Restart Home Assistant.

## Setup

My Home Assistant shortcut:

[![](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=stromligning)

Or go to Home Assistant > Settings > Integrations

Add "Stromligning" integration _(If it doesn't show, try CTRL+F5 to force a refresh of the page)_

## Use the custom template to show the next x cheapest hours

Copy the `custom_templates/FindCheapestPrice.jinja` to the `custom_templates` directory in your config folder (if it doesn't exist then create the folder)
Reload Home Assistant and use the Jinja template by inserting the example below in a template sensor helper

```
{% from 'FindCheapestPeriod.jinja' import FindCheapestPeriod%}
{% set earliestStartTime = now() %}
{% set latestStartTime = now() + timedelta(days=2) %}
{% set periodLength = timedelta(hours=3) %}
{{ FindCheapestPeriod(earliestStartTime , latestStartTime , periodLength, false) }}
```

This will result in a sensor showing the cheapest 3 hours within the known prices
