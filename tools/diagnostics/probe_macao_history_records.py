import requests


headers = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "cache-control": "no-cache",
    "origin": "https://288.pet",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": "https://288.pet/",
    "sec-ch-ua": "\"Microsoft Edge\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
}
url = "https://macao.zhifu.qpon/api/openApi/lottery/draw"
params = {
    "pageNum": "1",
    "pageSize": "20"
}
response = requests.get(url, headers=headers, params=params)

print(response.text)
print(response)