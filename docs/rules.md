# Rules for the Mesa move

These are the rules we follow. If the data shows a problem this page does not cover, we stop and add a rule before we load anything.

## What we leave out

Ocotillo Place is building B-09. Mesa sold it in March and deleted the building. Its apartments and its leases stay out. The tenants stay, because Mesa is still collecting from a couple of them.

Draft leases stay out. In the old system those are marked D. Carmen said a draft is just an idea the leasing team typed in. It is not a real lease yet. We list each one for her.

We do not make up a missing piece. If Keystone requires a value and the old record does not have it, and we cannot read it from somewhere else in the old data, the record stays out. Carmen gets a line that says what is missing.

## What we load

Pending, active, notice, ended, and cancelled leases load when the rest of the data is good. Those are real records.

If two old records are the same real person or the same real company, we load one. We keep one tenant number and point their leases and their people at that one. Carmen's spreadsheet says which number we kept.

We treat two records as the same person only when it is clear:

- The same name, and the same email or the same phone.
- Or a pair that is obviously the same person typed in again when they came back.

The same name by itself is not enough. Those stay as two people.

If we cannot tell which copy to keep, we do not pick one. Both lines go to Carmen, and we do not load the one we are unsure about.

## Cleaning we will do

We tell Carmen every time we change something.

- Extra spaces come off.
- Emails go to lowercase.
- A phone becomes +1 and 10 digits when those 10 digits are really there. If they are not, we leave the phone off and still load the person.
- A ZIP written as 85004-1234 becomes 85004. We say we kept the first five digits.
- A state written as a full name, like Arizona, becomes AZ when that is obviously the same thing.

Time zones were typed in by site managers. Keystone needs an official name, and it will not save a building without one. We read the words they typed like this, and we tell Carmen the exact word and the name we used:

- Arizona, or MST on a building in Arizona: America/Phoenix. Arizona does not switch for daylight saving.
- MST, Mountain, or MT on a building outside Arizona: America/Denver.
- CST or Central: America/Chicago.
- Pacific, PST, or PT: America/Los_Angeles.

If the city and the time zone disagree, we still follow the word they typed, and we say so. El Paso is the one to watch. If the file says CST, we use Central time and ask Carmen to confirm, because El Paso usually runs on Mountain time.

If a time zone is a word we do not recognize, that building stays out, and so do its apartments and leases.

## Money rules and lease rules

Companies marked "needs a PO" must have a PO number on every lease. If the PO is blank, that lease stays out. We ask Carmen for the number.

A lease needs at least one rent charge. We do not invent a rent line. Parking, pet, and storage can come along with a real rent line. If the only charges are not rent, the lease stays out.

If the end date is before the start date, the lease stays out.

Two leases cannot both be active, or on notice, for the same apartment on the same days. We keep the one that is clearly the current lease. The other one goes to Carmen, with both lease numbers named.

## Vendors

Vendor payment terms were typed as free text. Keystone only accepts due on receipt, net 10, net 15, net 30, net 45, and net 60. If we can read the text as one of those, we use it and tell Carmen. If we cannot, that vendor stays out. An apartment can still load without a maintenance vendor.

## How we send the data

We wipe Keystone once, right before the real load. Then we send records in this order, because each one needs the one above it:

1. Portfolios
2. Vendor payment terms
3. Floor plans
4. Accounts, parents first
5. Buildings
6. Vendors
7. People on the accounts
8. The main contact on each account
9. Apartments
10. Leases, with their charges

Keystone sometimes says a save failed when it actually worked. Every save gets its own key, so a retry cannot create a second copy. We go slowly so we stay under the speed limit.

## The review spreadsheets

Clean records stay out of the review. Carmen's files are the exception list.

Each file starts with the blank template columns, unchanged. Then we add four columns:

- legacy_id: the old id
- load_status: not_loaded, or loaded_with_changes
- issue: what is wrong, in a normal sentence
- what_we_need_from_you: what Carmen should do
