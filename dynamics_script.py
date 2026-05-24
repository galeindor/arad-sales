from dynamics_consts import *
import requests

def get_access_token() -> str:
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    token_response = requests.post(token_url, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": f"{CRM_URL}/.default",
    })
    access_token = token_response.json()["access_token"]
    return access_token


def get_headers(access_token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }
    return headers


def build_contact_data() -> dict:
    contact_data = {
        "firstname": 'itamar_first_test',
        "lastname": 'itamar_last_test',
        "emailaddress1": 'itamar.test@gmail.com',
        "statecode": 0,   # 0 = Active
        "statuscode": 1,  # 1 = Active
    }
    return contact_data


def create_contact(headers: dict, contact_data: dict):
    response = requests.post(
        f"{CRM_URL}/api/data/v9.2/contacts",
        headers=headers,
        json=contact_data
    )
    return response


def get_campaign_id(headers: dict, campaign_name: str, created_on: str = None) -> str:
    """
    Get campaign ID by name.
    created_on: optional date string 'YYYY-MM-DD' to disambiguate campaigns with the same name.
    """
    url = f"{CRM_URL}/api/data/v9.2/campaigns"

    filter_str = f"name eq '{campaign_name}'"
    if created_on:
        filter_str += f" and createdon ge {created_on}T00:00:00Z and createdon lt {created_on}T23:59:59Z"

    params = {
        "$select": "campaignid,name,createdon",
        "$filter": filter_str,
    }
    response = requests.get(url, headers=headers, params=params)
    results = response.json().get("value", [])
    if not results:
        raise ValueError(f"Campaign '{campaign_name}' not found")
    return results[0]["campaignid"]


def get_marketing_lists(headers: dict, campaign_id: str) -> list:
    """Get all marketing lists linked to a campaign via the Campaign Item table"""
    url = f"{CRM_URL}/api/data/v9.2/campaignitems"
    params = {
        "$select": "entityid,entitytype",
        "$filter": f"_campaignid_value eq {campaign_id} and entitytype eq 'list'"
    }
    response = requests.get(url, headers=headers, params=params)
    items = response.json().get("value", [])

    result = []
    for item in items:
        list_id = item["entityid"]
        list_url = f"{CRM_URL}/api/data/v9.2/lists({list_id})"
        list_response = requests.get(list_url, headers=headers, params={"$select": "listid,listname"})
        list_data = list_response.json()
        result.append({
            "listid": list_data.get("listid"),
            "listname": list_data.get("listname")
        })
    return result


def _fetch_member_details(headers: dict, members: list) -> list:
    """Fetch contact/account details for static list members"""
    result = []
    for m in members:
        entity_id = m.get("_entityid_value")
        entity_type = m.get("entitytype")
        if entity_type == "contact":
            r = requests.get(f"{CRM_URL}/api/data/v9.2/contacts({entity_id})", headers=headers,
                             params={"$select": "contactid,firstname,lastname,fullname,emailaddress1,mobilephone,telephone1"})
            c = r.json()
            result.append({
                "type":       "contact",
                "id":         c.get("contactid"),
                "first_name": c.get("firstname"),
                "last_name":  c.get("lastname"),
                "full_name":  c.get("fullname"),
                "email":      c.get("emailaddress1"),
                "phone":      c.get("mobilephone") or c.get("telephone1"),
            })
        elif entity_type == "account":
            r = requests.get(f"{CRM_URL}/api/data/v9.2/accounts({entity_id})", headers=headers,
                             params={"$select": "accountid,name,emailaddress1,telephone1,telephone2"})
            a = r.json()
            result.append({
                "type":      "account",
                "id":        a.get("accountid"),
                "full_name": a.get("name"),
                "email":     a.get("emailaddress1"),
                "phone":     a.get("telephone1") or a.get("telephone2"),
            })
    return result

def main():
    # Dynamics setup
    access_token = get_access_token()
    headers = get_headers(access_token)

    camp_name = "בדיקה"
    campaign_id = get_campaign_id(headers, camp_name, created_on="2025-04-22")

    # Getting camp marketing lists
    # TODO: change to work with id^
    campaign_data = get_campaign_lists_with_members(headers, camp_name, created_on="2025-04-22")
    for list_name, members in campaign_data.items():
        print(f"\n--- {list_name} ({len(members)} members) ---")
        for member in members:
            print(member)

    # Combining lists
    combined = combine_lists(campaign_data)
    print(f"\n--- COMBINED ({len(combined)} members) ---")
    for member in combined:
        print(member)

    # Create a new group in AT and add the contacts
    group_id = create_at_group('test group 2')
    import_contacts_to_group(group_id, combined)

    # Assign group to campaign in AT
    at_campaign_id = get_campaign_id_by_name(camp_name)
    assign_group_to_campaign(at_campaign_id, group_id)

    # Get all campaign responses for a campaign
    responses = get_campaign_responses(headers, campaign_id)

    # TODO: remove example: update the response for a specific contact
    contact_id = "95c0d71b-6e69-ec11-8943-000d3ade3ba6"  # Keren Shahar

    target_response = next(
        (r for r in responses if r.get("_rtm_l_contact_value") == contact_id),
        None
    )

    if target_response:
        update_campaign_response(
            headers,
            activity_id=target_response["activityid"],
            status_code=1,
            subject="test subject 123",
            description="test description 123",
        )
    else:
        print(f"No campaign response found for contact {contact_id}")


if __name__ == "__main__":
    main()
