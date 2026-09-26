# StockSense UI Specification

Source: [StockSense - 8 hours.svg](StockSense%20-%208%20hours.svg)

This document describes the complete UI board, including the visible screens, exact copy, navigation, sample data, statuses, and interaction requirements. Text is preserved as it appears in the source design, including spelling and grammar.

## 1. Overall visual direction

- The source is a dark-background wireframe/design board.
- Main canvas/background color: `#121212`.
- Primary accent color: `#ff8383` pink/coral, used for outlines, controls, buttons, and emphasis.
- Secondary light color: `#d3d3d3`, used for supporting text and lighter UI marks.
- The design uses a hand-drawn/wireframe visual language with rounded outlined controls and cards.
- The authenticated application uses a repeated top navigation bar.
- Repeated authenticated navigation items are:
  - `Dashboard`
  - `Operations`
  - `Products` / `Stock` depending on the screen
  - `Move History`
  - `Settings`
  - `A` — user/avatar placeholder
- Primary text is generally around 16px, with 20px headings and larger labels for page titles or cards.

## 2. Authentication flow

### 2.1 Login screen

The login screen contains:

- App logo placeholder: `App Logo`
- Login field label: `Login Id`
- Password field label: `Password`
- Primary button: `SIGN IN`
- Inline links: `Forget Password ? | Sign Up`

#### Login behavior notes shown in the design

- `- Check for Login Credentials`
- `-Match creds, and allow to login a user`
- `-If Creds does not match thrw an error msg,`
- Error text: `"Invalid Login Id or Password"`
- `- When clicked on SignUp, Land to SignUp page`
- `-When Clicked on Forget Password click on Forget Password page`

### 2.2 Sign-up screen

The sign-up screen contains these fields:

- `Enter Login Id`
- `Enter Password`
- `Re-Enter Password`
- `Enter Email Id`
- Primary button: `SIGN UP`

The authentication board also labels the two destinations/tabs as:

- `Login Page`
- `Sign up Page`

#### Sign-up implementation notes shown in the design

- `For Sign up Page,`
- `Ceate a user database into the system on signup`
- `Check creds as follows`
- `1. login ID should be unique and must be in between 6-12 charachters.`
- `2. Email Id should not be a duplicate in database`
- `3.Password must me unique and must contain a small case, a large case and`
- `a special character and length should be in more then 8 charachters.`

## 3. Dashboard

The dashboard is the first authenticated landing page and uses the common top navigation.

### Navigation on dashboard

- `Dashboard`
- `Operations`
- `Stock`
- `Move History`
- `Settings`
- `A`

### Dashboard content

The dashboard shows summary cards for receipt and delivery operations.

#### Receipt summary card

- Title: `Reciept`
- Metric: `4 to receive`
- Alert metric: `1 Late`
- Operations metric: `6 operations`

#### Delivery summary card

- Title: `Delivery`
- Metric: `4 to Deliver`
- Alert metric: `1 Late`
- Waiting metric: `2 waiting`
- Operations metric: `6 operations`

### Dashboard behavior notes

- `Dashboard to display the`
- `current statistics`
- `Operation can be`
- `perform Submenu`
- `1. Reciept`
- `2. Delivery`
- `3. Adjustment`
- `List the available stock`
- `Display the history`
- `of In/Out stocks`
- `1. Warehouse`
- `2. Locations`

The dashboard therefore acts as a summary and launch point for operations, stock, warehouse/location data, and inventory movement history.

## 4. Operations area

The Operations area has three intended submenus:

1. `Reciept`
2. `Delivery`
3. `Adjustment`

The SVG provides detailed list and detail screens for Receipt and Delivery. Adjustment is named as a submenu but does not have a dedicated detailed screen in this board.

## 5. Receipt list screen

### Navigation

The receipt list screen repeats the authenticated navigation:

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Page header and view behavior

- Page title: `Reciepts`
- `By default land on List View`
- The user can switch to a kanban view based on status.

### List columns

- `Reference`
- `Contact`
- `Schedule date`
- `Status`

### Sample rows

| Reference | Contact | Status |
|---|---|---|
| `WH/IN/0001` | `Azure Interior` | `Ready` |
| `WH/IN/0002` | `Azure Interior` | `Ready` |

### Receipt list requirements

- `Populate all work orders added to manufacturing order`
- `Allow user to search receptive based on reference & contacts`
- `Allow user to switch to the kanban view based on status`

Note: The word `receptive` is preserved exactly from the source; the intended meaning appears to be receipt records.

## 6. Delivery list screen

### Navigation

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Page header and view behavior

- Page title: `Delivery`
- `By default land on List View`
- The user can switch to a kanban view based on status.

### List columns

- `Reference`
- `Contact`
- `Schedule date`
- `Status`

### Sample rows

| Reference | Contact | Status |
|---|---|---|
| `WH/OUT/0001` | `Azure Interior` | `Ready` |
| `WH/OUT/0002` | `Azure Interior` | `Ready` |

### Delivery list requirements

- `Populate all delivery orders`
- `Allow user to search Delivery based on reference & contacts`
- `Allow user to switch to the kanban view based on status`

## 7. Reference-number rules

The reference should be generated automatically and incremented.

Exact source notes:

- `Reference should be auto`
- `increment & follow the below`
- `structer`
- Example: `WH/IN/001`
- Pattern: `<Warehouse>/<Operation>/<ID>`
- `Warehouse = Id of warehouse`
- `operation = IN/OUT`
- `Id = auto incremental unique id`

Implementation interpretation:

- Warehouse is represented by the warehouse code/identifier.
- Operation is `IN` for receipts and `OUT` for deliveries.
- ID is a unique auto-incrementing sequence.
- Example receipt reference: `WH/IN/0001`.
- Example delivery reference: `WH/OUT/0001`.

## 8. Warehouse screen

The warehouse screen uses the common authenticated navigation:

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Page content

- Page title: `Warehouse`
- Field label: `Name:`
- Field label: `Short Code:`
- Field label: `Address:`

The screen is intended for creating or editing warehouse identity and address information.

## 9. Stock screen

The stock screen uses the common navigation and is described as the available inventory view.

### Page content

- Page title: `Stock`
- Description: `This page contains the warehouse details & location.`
- Table headings/labels:
  - `Product per unit cost`
  - `On hand`
  - `free to Use`

### Sample stock data

| Product | Unit cost | On hand | Free to use |
|---|---:|---:|---:|
| `Desk` | `3000 Rs` | `50` | `45` |
| `Table` | `3000 Rs` | `50` | `50` |

### Stock requirements

- `User must be able to update the stock from here.`
- Stock status/date rules:
  - `Late: schedule date < today's date`
  - `Operations: schedule date > today's date`
  - `Waiting: Waiting for the stocks`

## 10. Location screen

The location screen uses the common navigation:

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Page content

- Page title: `location`
- Field label: `Name:`
- Field label: `Short Code:`
- Field label: `warehouse:`
- Description: `This holds the multiple locations of warehouse, rooms etc..`

### Location examples and relationships

The board shows these labels/values:

- `WH`
- `From`
- `To`
- `vendor`
- `vendor`
- `From`
- `To`
- `WH/Stock1`
- `WH/Stock1`
- `vendor`
- `vendor`
- `WH/Stock1`
- `WH/Stock1`
- `Locations of warehouse`

The intended model is a warehouse containing multiple locations, rooms, vendor locations, and stock locations. Locations are used as From/To endpoints for inventory movements.

## 11. Receipt detail screen

### Navigation

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Header and metadata

- Page title: `Receipt`
- Reference: `WH/IN/0001`
- Field: `Receive From`
- Field: `Schedule Date`
- Status flow: `Draft > Ready > Done`

### Actions

- `New`
- `Validate`
- `Print`
- `Cancel`

The source contains the action label `NEW` as well as `New`; treat this as the same New action rendered in different parts of the board.

### Responsibility and product lines

- Field: `Responsible`
- Section title: `Products`
- Action: `New Product`
- Product column: `Product`
- Quantity column: `Quantity`
- Sample product: `[DESK001] Desk`
- Sample quantity: `6`

### Receipt behavior notes

- `To DO = When in Draft`
- `Validate = When in Ready`
- `On click, TODO, move to Ready`
- `onclick, Validate move to Done`
- `Print the receipt once it's DONE`

Receipt status definitions:

- `Draft - Initial stage`
- `Ready - Ready to receive`
- `Done - Recieved`

The board also includes the generic status definition:

- `Draft: Initial state`
- `Waiting: Waiting for the out of stock product to be in`
- `Ready: Ready to deliver/receive`
- `Done: Received or delivered`

## 12. Delivery detail screen

### Navigation

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Header and metadata

- Page title: `Delivery`
- Reference: `WH/OUT/0001`
- Field: `Delivery Adress`
- Field: `Schedule Date`
- Field: `Operation type`
- Status flow: `Draft > Waiting> Ready > Done`

### Actions

- `New`
- `Validate`
- `Print`
- `Cancel`

### Responsibility and product lines

- Field: `Responsible`
- Section title: `Products`
- Action: `New Product`
- Product column: `Product`
- Quantity column: `Quantity`
- Sample product: `[DESK001] Desk`
- Sample quantity: `6`

### Delivery behavior notes

- `To DO = When in Draft`
- `Validate = When in Ready`
- `On click, TODO, move to Ready`
- `onclick, Validate move to Done`
- `Print the receipt once it's DONE`

Generic status definitions shown on the board:

- `Draft: Initial state`
- `Waiting: Waiting for the out of stock product to be in`
- `Ready: Ready to deliver/receive`
- `Done: Received or delivered`

## 13. Move History screen

### Navigation

- `Dashboard`
- `Operations`
- `Products`
- `Move History`
- `Settings`
- `A`

### Page header and view behavior

- Page title: `Move History`
- `By default land on List View`
- The user can switch to a kanban view based on status.

### List columns

- `Reference`
- `Contact`
- `Status`
- `From`
- `To`
- `Quantity`
- `Date`

### Sample move rows

| Reference | Contact | Status | Date | From | To | Quantity |
|---|---|---|---|---|---|---|
| `WH/IN/0001` | `Azure Interior` | `Ready` | `12/1/2001` | — | — | — |
| `WH/OUT/0002` | `Azure Interior` | `Ready` | `12/1/2001` | `WH/Stock1` | `vendor` | — |

Additional sample location values shown:

- `WH/Stock1`
- `WH/Stock2`
- `vendor`

### Move History requirements

- `Populate all moves done between the from - To`
- `location in inventory`
- `if single reference has multiple product display it`
- `in multiple rows.`
- `In event should be display in green`
- `Out moves should be display in rend`
- `Allow user to search Delivery based on reference & contacts`
- `Allow user to switch to the kanban view based on status`

The move history should expand a reference with multiple products into multiple rows. Incoming moves should be visually green; outgoing moves should be visually red. The source spells `rend`; the intended color is red.

## 14. Products and new-product flow

The authenticated navigation includes `Products`, and both receipt and delivery detail screens include:

- `Products`
- `New Product`
- `Product`
- `Quantity`
- `[DESK001] Desk`
- `6`

The board also contains the standalone requirement:

- `Add New product`

This implies a product creation flow should be reachable from the Products area and/or from the New Product action inside an operation.

## 15. Logged-in user behavior

The board includes this requirement:

- `Auto fill with the current logged in`
- `users.`

The `Responsible` field on operation detail screens should therefore default to the currently logged-in user where appropriate.

## 16. Notifications and stock validation

The board specifies:

- `Alert the notification & mark the line red if`
- `product is not in stock.`

Implementation behavior:

- When a delivery or other outbound operation requests a product that is unavailable, show a notification/alert.
- Mark the affected product line red.
- The operation may remain in a waiting state until the required stock exists.
- The status wording connected to this behavior is `Waiting: Waiting for the out of stock product to be in`.

## 17. Status model

The UI uses status to drive list rows, kanban cards, actions, colors, and dashboard counts.

### Receipt statuses

- `Draft`
- `Ready`
- `Done`

Flow: `Draft > Ready > Done`

### Delivery statuses

- `Draft`
- `Waiting`
- `Ready`
- `Done`

Flow: `Draft > Waiting> Ready > Done`

### Action rules

- Draft is the initial state.
- `To DO` is available/used when the record is in Draft.
- Clicking `TODO` moves the record to Ready.
- `Validate` is used when the record is Ready.
- Clicking `Validate` moves the record to Done.
- Print the receipt once the record is Done.
- Waiting is used when an outbound operation is blocked by missing stock.

## 18. Search, view, and navigation requirements

- After login, land on the Dashboard.
- Clicking `Sign Up` opens the Sign-up page.
- Clicking `Forget Password ?` opens the Forget Password page. The board names the destination but does not provide a detailed Forget Password screen.
- Dashboard operation cards should link to Receipt and Delivery lists.
- Operations exposes Receipt, Delivery, and Adjustment submenus.
- List screens load in List View by default.
- List screens can switch to Kanban View based on status.
- Receipt search uses reference and contact.
- Delivery search uses reference and contact.
- Move History search uses reference and contact; the source labels this as Delivery search, but the same behavior should apply to move records.
- Products provides access to product records and adding a new product.
- Stock allows stock updates.
- Warehouse and Location screens manage warehouse structure and endpoints.

## 19. Exact-copy inventory

For implementation QA, these are all visible text strings extracted from the design board:

`Login Id`, `Password`, `Forget Password ? | Sign Up`, `App Logo`, `SIGN IN`, `- Check for Login Credentials`, `-Match creds, and allow to login a user`, `-If Creds does not match thrw an error msg,`, `"Invalid Login Id or Password"`, `- When clicked on SignUp, Land to SignUp page`, `-When Clicked on Forget Password click on Forget Password page`, `SIGN UP`, `Login Page`, `Sign up Page`, `For Sign up Page,`, `Ceate a user database into the system on signup`, `Check creds as follows`, `1. login ID should be unique and must be in between 6-12 charachters.`, `2. Email Id should not be a duplicate in database`, `3.Password must me unique and must contain a small case, a large case and`, `a special character and length should be in more then 8 charachters.`, `Enter Login Id`, `Enter Password`, `Re-Enter Password`, `Enter Email Id`, `Login/Signup`, `Dashboard`, `Reciept`, `4 to receive`, `1 Late`, `6 operations`, `Delivery`, `4 to Deliver`, `2 waiting`, `Operations`, `Stock`, `Move History`, `Settings`, `4 to Deliver`, `4 to receive`, `1. Reciept`, `2. Delivery`, `3. Adjustment`, `Dashboard to display the`, `current statistics`, `Operation can be`, `perform Submenu`, `List the available stock`, `Display the history`, `of In/Out stocks`, `1. Warehouse`, `2. Locations`, `Reciepts`, `By default land on List View`, `Reference`, `Contact`, `Schedule date`, `Status`, `WH/IN/0001`, `Azure Interior`, `Ready`, `Populate all work orders added to manufacturing order`, `Allow user to search receptive based on reference & contacts`, `WH/IN/0002`, `Allow user to switch to the kanban view based on status`, `WH/OUT/0001`, `WH/OUT/0002`, `Populate all delivery orders`, `Allow user to search Delivery based on reference & contacts`, `Reference should be auto`, `increment & follow the below`, `structer`, `WH/IN/001`, `<Warehouse>/<Operation>/<ID>`, `Warehouse = Id of warehouse`, `operation = IN/OUT`, `Id = auto incremental unique id`, `Warehouse`, `Name:`, `Short Code:`, `Address:`, `Receipt`, `Receive From`, `Schedule Date`, `Draft > Ready > Done`, `NEW`, `New`, `Validate`, `Print`, `Cancel`, `Responsible`, `Products`, `New Product`, `Product`, `Quantity`, `[DESK001] Desk`, `6`, `Delivery Adress`, `Operation type`, `Draft > Waiting> Ready > Done`, `When user click on receipt operations`, `When user click on Delivery operations`, `When user click on Move History`, `Move History`, `Date`, `12/1/2001`, `To DO = When in Draft`, `Validate = When in Ready`, `On click, TODO, move to Ready`, `onclick, Validate move to Done`, `Print the receipt once it's DONE`, `Draft: Initial state`, `Waiting: Waiting for the out of stock product to be in`, `Ready: Ready to deliver/receive`, `Done: Received or delivered`, `Draft - Initial stage`, `Ready - Ready to receive`, `Done - Recieved`, `Alert the notification & mark the line red if`, `product is not in stock.`, `Add New product`, `This page contains the warehouse details & location.`, `Product per unit cost On hand free to Use`, `Desk`, `3000 Rs`, `50`, `45`, `Table`, `User must be able to update the stock from here.`, `Late: schedule date < today's date`, `Operations: schedule date > today's date`, `Waiting: Waiting for the stocks`, `Auto fill with the current logged in`, `users.`, `location`, `warehouse:`, `This holds the multiple locations of warehouse, rooms etc..`, `WH`, `From`, `To`, `vendor`, `WH/Stock1`, `Locations of warehouse`, `WH/Stock2`.

## 20. Implementation checklist

- [ ] Dark theme with pink/coral outlined wireframe styling.
- [ ] Login page with validation and error state.
- [ ] Sign-up page with unique Login ID, unique email, and password rules.
- [ ] Forget Password route/link.
- [ ] Dashboard with Receipt and Delivery summary cards.
- [ ] Operations submenu with Receipt, Delivery, and Adjustment.
- [ ] Receipt list with search, status, List View, and Kanban View.
- [ ] Delivery list with search, status, List View, and Kanban View.
- [ ] Automatic reference generation using `<Warehouse>/<Operation>/<ID>`.
- [ ] Warehouse create/edit screen.
- [ ] Stock table with editable inventory values.
- [ ] Location create/edit screen and From/To location data.
- [ ] Receipt detail screen with status flow and actions.
- [ ] Delivery detail screen with status flow and actions.
- [ ] Product lines with product and quantity.
- [ ] New Product action and product creation flow.
- [ ] Move History list with From, To, Quantity, Date, and status.
- [ ] Multiple rows when one reference contains multiple products.
- [ ] Green incoming moves and red outgoing moves.
- [ ] Stock shortage notification and red affected product line.
- [ ] Responsible field auto-filled from the logged-in user.
- [ ] Print allowed after Done status.
