from urllib.parse import urlparse, parse_qs

def test_extraction(search_url):
    parsed_url = urlparse(search_url)
    query_params = parse_qs(parsed_url.query)
    
    # Extract keywords
    keywords = query_params.get('keywords', [''])[0]
    
    # Extract geoId (location)
    location = query_params.get('geoId', [''])[0]
    
    remote_map = {'1': 'onsite', '2': 'remote', '3': 'hybrid'}
    f_wt = query_params.get('f_WT', [])
    if f_wt:
        first_wt = f_wt[0].split(',')[0]
        remote = remote_map.get(first_wt, "")
    else:
        remote = ""

    exp_map = {
        '1': 'internship',
        '2': 'entry',
        '3': 'associate',
        '4': 'mid_senior',
        '5': 'director',
        '6': 'executive'
    }
    f_e = query_params.get('f_E', [])
    if f_e:
        first_e = f_e[0].split(',')[0]
        experience_level = exp_map.get(first_e, "")
    else:
        experience_level = ""

    run_input = {
        "keywords": keywords,
        "location": location,
        "remote": remote,
        "experienceLevel": experience_level,
    }
    return run_input

urls = [
    "https://www.linkedin.com/jobs/search/?currentJobId=4312026327&f_E=3%2C4&f_TPR=r604800&f_WT=2&geoId=103350119&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_LOCATION_HISTORY&refresh=True&sortBy=R",
    "https://www.linkedin.com/jobs/search/?currentJobId=4313461130&f_E=3%2C4&f_TPR=r604800&f_WT=1%2C2%2C3&geoId=106398949&keywords=(software%20OR%20%22data%20Engineer%22%20OR%20Backend%20OR%20%22back%20End%22%20OR%20%22ai%20Engineer%22%20OR%20%22aritifical%20Inteligence%20Engineer%22%20OR%20%22ml%20Engineer%22)%20AND%20NOT%20(%22php%22%20OR%20%22full%20Stack%22%20OR%20%22kubernetes%22%20OR%20%22frontend%22%20OR%20%22android%22%20OR%20%22angular%22%20OR%20%22network%22%20OR%20%22manager%22%20OR%20%22research%22)&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=True&sortBy=R"
]

for url in urls:
    result = test_extraction(url)
    print(f"URL: {url[:100]}...")
    print(f"Result: {result}")
    for k, v in result.items():
        if not isinstance(v, str):
            print(f"FAILURE: {k} is not a string!")
