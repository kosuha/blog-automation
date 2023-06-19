from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import NewPost
from wordpress_xmlrpc.methods.taxonomies import GetTerms, NewTerm
from wordpress_xmlrpc.methods import posts, media
from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc import WordPressTerm
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import requests
import openai
import config.config as conf

# openai
openai.api_key = conf.openai_key

# 스프레스시트 
scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
json_file_name = "./config/trading-bot-386403-553aeec26efe.json"
credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file_name, scope)
gc = gspread.authorize(credentials)

doc = gc.open_by_url(conf.spreadsheet_url)

# wordpress

wp = Client(conf.wp_url, conf.wp_username, conf.wp_password)

def create_category(wp, category_name):
    categories = wp.call(GetTerms('category'))
    category_names = [category.name for category in categories]

    if category_name not in category_names:
        new_category = WordPressTerm()
        new_category.taxonomy = 'category'
        new_category.name = category_name
        new_category_id = wp.call(NewTerm(new_category))

def publish_post(title, categorys, attachment_id, content):
    for c in categorys:
        create_category(wp, c.strip())

    post = WordPressPost()
    post.title = title
    post.content = content
    post.thumbnail = attachment_id  # Set featured image
    post.terms_names = {
    'category': categorys
    }
    post.post_status = 'publish'
    wp.call(NewPost(post))

def get_recipe_prompt(name):
    prompt = f"""
    i want to get recipe of {name}.
    i have a form like this.
    
    name%%%title%%%categories%%%description%%%content
    this form will splited by "%%%".
    it's example of form.

    불고기%%%Recipe: Bulgogi%%%Recipes,Korean Cuisine%%%Bulgogi, a traditional Korean dish, is a crowd pleaser known for its flavorful marinade and tender slices of beef. It's the perfect introduction to Korean cuisine.%%%<p>Bulgogi, a traditional Korean dish, is a crowd pleaser known for its flavorful marinade and tender slices of beef. It's the perfect introduction to Korean cuisine.</p><br><h2>Ingredients:</h2><ul><li>500g of beef (sirloin or ribeye), thinly sliced</li><li>1/2 cup of soy sauce</li><li>3 tablespoons of sugar</li><li>2 tablespoons of honey</li><li>2 tablespoons of sesame oil</li><li>3 cloves of garlic, minced</li><li>1 medium onion, thinly sliced</li><li>2 green onions, chopped</li><li>2 tablespoons of toasted sesame seeds</li><li>1/2 teaspoon of black pepper</li><li>1 pear, pureed (optional for additional sweetness and tenderizing)</li></ul><h2>Instructions:</h2><ol><li>In a bowl, mix the soy sauce, sugar, honey, sesame oil, garlic, black pepper, and pear (if using) to make the marinade.</li><li>Add the thinly sliced beef to the marinade and mix well. Let it marinate for at least 1 hour, or for best results, overnight in the refrigerator.</li><li>In a pan, add the marinated beef along with the marinade. Stir-fry over medium heat until the beef is cooked through and browned.</li><li>Add the sliced onion to the pan and continue to cook until the onion is translucent.</li><li>Sprinkle the chopped green onions and toasted sesame seeds over the top of the bulgogi before serving. Bulgogi is often served with a side of rice and lettuce for wrapping.</li></ol>

    "title" is English name of dish.
    "title" is prefixed with "Recipe:". (title example: "Recipe: Bulgogi")
    so, write recipe about "{name}" at "content". like this form.
    And, description for this cuisine at the top of "content" in <p> tag is more than 300 characters.
    this description is same with "description" at the form.
    oh, write only form you create... with no other words.
    don't print "name%%%title%%%categories%%%description%%%content".
    
    """
    return prompt

def get_dishes_prompt(excepted_dishes):
    excepted_str = ""
    for i in range(len(excepted_dishes)):
        excepted_str += excepted_dishes[i]
        if i != (len(excepted_dishes) - 1):
            excepted_str += ", "

    prompt = f"""
    i want answer as 5 word.
    Please recommend five good dishes to cook at home like this example form.
    i already know {excepted_str}.
    so must except for these dishes({excepted_str}).
    i will search recipes. so these dishes must be specific cuisine.
    for example, i want not just sushi... salmon sushi, not just pizza.. potato pizza.
    Aside from the ones below, I also like a variety of foods from around the world.
    form have to splited by '%%%'.
    oh, write only form you create... with no other words.

    example:
    Biryani%%%bulgogi%%%tacos%%%Pad Thai%%%Ratatouille
    """
    return prompt

def main():
    while True:
        worksheet = doc.worksheet('data')
        values = worksheet.get_values()
        for i in range(len(values)):
            if values[i][5] == '0':
                try:
                    # 이미지 파일을 워드프레스 서버에 업로드
                    response = openai.Image.create(
                        prompt=values[i][4],
                        n=1,
                        size="512x512"
                    )
                    image_url = response['data'][0]['url']
                    image_data = requests.get(image_url).content
                    data = {
                            'name': 'image_name.jpg',
                            'type': 'image/jpeg',  # mimetype
                            'bits': xmlrpc_client.Binary(image_data)
                        }
                    response = wp.call(media.UploadFile(data))
                    attachment_id = response['id']

                    categorys = values[i][2].split(',')
                    publish_post(title=values[i][1], categorys=categorys, attachment_id=attachment_id ,content=values[i][3])
                    worksheet.update_acell('F' + str(i + 1), '1')
                    time.sleep(3600 * 3)
                except Exception as e:
                    print(e)
                    worksheet.update_acell('F' + str(i + 1), '2')
                    time.sleep(60)

        column_data = worksheet.col_values(1)
        column_data = column_data[1:]
        dishes_prompt = get_dishes_prompt(column_data)
        dishes_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {conf.openai_key}"},
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": dishes_prompt}]},
        )
        dishes_str = dishes_response.json()["choices"][0]["message"]["content"]
        dishes = dishes_str.split('%%%')
        time.sleep(5)

        for dish in dishes:
            try:
                recipe_prompt = get_recipe_prompt(dish)
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {conf.openai_key}"},
                    json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": recipe_prompt}]},
                )
                recipes_str = response.json()["choices"][0]["message"]["content"]
                recipes_str = recipes_str.replace("\n", "")
                recipes = recipes_str.split('%%%')
                worksheet.append_row([recipes[0], recipes[1], recipes[2], recipes[4], recipes[3], 0])
            except Exception as e:
                print(e)
            time.sleep(5)

        time.sleep(180)

main()