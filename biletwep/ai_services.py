import google.generativeai as genai
import json
import os
import re

class AICurator:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        print(f"AI Service Initialized with model: gemini-2.5-flash")

    def explain_pair(self, user_profile, pair):
        """
        Asks Gemini to explain why the selected pair is good.
        """
        if not pair or len(pair) < 2:
            return None

        # Etkinlik detaylarını topla
        events_details = []
        for i, event in enumerate(pair, 1):
            # Venue bilgisi
            venue_name = 'Mekan belirtilmemiş'
            if event.get('venue'):
                if isinstance(event['venue'], dict):
                    venue_name = event['venue'].get('name', 'Mekan belirtilmemiş')
                else:
                    venue_name = str(event['venue'])
            
            # Kategori bilgisi
            category_name = 'Genel'
            if event.get('category'):
                if isinstance(event['category'], dict):
                    category_name = event['category'].get('name', 'Genel')
                else:
                    category_name = str(event['category'])
            
            # Tarih bilgisi
            start_time = event.get('start') or event.get('date') or 'Tarih belirtilmemiş'
            
            # Fiyat bilgisi
            price_info = 'Ücretsiz' if event.get('is_free') else f"{event.get('ticket_price', 'Fiyat belirtilmemiş')} TL"
            
            # Açıklama/Özet
            description = event.get('description') or event.get('overview') or event.get('summary') or ''
            
            event_detail = f"""
Etkinlik {i}: {event.get('name', 'Etkinlik')}
- Kategori: {category_name}
- Mekan: {venue_name}
- Tarih: {start_time}
- Fiyat: {price_info}
- Açıklama: {description[:300] if description else 'Bu etkinlik hakkında detaylı bilgi mevcut değil.'}
"""
            events_details.append({
                'detail': event_detail,
                'name': event.get('name', 'Etkinlik'),
                'category': category_name
            })

        user_interests = ', '.join(user_profile.get('interests_list', [])) or 'Çeşitli ilgi alanları'
        user_budget = user_profile.get('budget', 'Belirtilmemiş')

        prompt = f"""Sen bir etkinlik uzmanısın. Aşağıdaki kullanıcıya önerilen iki etkinlik hakkında samimi ve içten yorumlar yaz.

{events_details[0]['detail']}

{events_details[1]['detail']}

Kullanıcı Profili:
- İlgi Alanları: {user_interests}
- Bütçe: {user_budget} TL

GÖREV: Her etkinlik için 2-3 cümlelik bir yorum yaz. Yorumlarında:
- Etkinliğin öne çıkan özelliklerinden bahset
- Kategorisine göre neden özel olduğunu anlat
- Kullanıcının ilgi alanlarıyla bağlantı kur
- Samimi ve davet edici bir dil kullan

Yanıtını SADECE şu JSON formatında ver, başka hiçbir şey yazma:
{{
  "event1_comment": "Birinci etkinlik hakkında yorum",
  "event2_comment": "İkinci etkinlik hakkında yorum"
}}"""

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.8,
                    top_p=0.9,
                )
            )
            
            # Response'u temizle
            text = response.text.strip()
            
            # Debug için
            print(f"Gemini Raw Response: {text[:200]}...")
            
            # JSON bloklarını temizle
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            
            # JSON'u bul (ilk { ile son } arası)
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]
            
            # JSON parse et
            result = json.loads(text)
            
            # Yorumları güzel formatta birleştir
            comment = f"""Bu etkinlikleri senin için özenle seçtik:

🎭 **{events_details[0]['name']}**
{result.get('event1_comment', 'Harika bir deneyim sunuyor!')}

🎪 **{events_details[1]['name']}**
{result.get('event2_comment', 'Unutulmaz anlar için mükemmel!')}"""
            
            return {"comment": comment}
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Parse Error: {e}")
            print(f"❌ Response text: {text if 'text' in locals() else 'No text'}")
            
            # Fallback: Kategori bazlı yorum
            return {
                "comment": f"""Bu etkinlikleri senin için seçtik:

🎭 **{events_details[0]['name']}**
{events_details[0]['category']} kategorisinde sana özel bir deneyim. {user_interests} ilgi alanına uygun, kaçırma!

🎪 **{events_details[1]['name']}**
{events_details[1]['category']} severler için harika bir fırsat. Bütçene uygun ve keyifli bir etkinlik."""
            }
            
        except Exception as e:
            print(f"❌ AI Error: {e}")
            print(f"❌ Full error: {str(e)}")
            
            # Fallback
            return {
                "comment": f"""Bu etkinlikleri senin için seçtik:

🎭 **{events_details[0]['name']}**
{events_details[0]['category']} kategorisinde özenle seçilmiş bir deneyim.

🎪 **{events_details[1]['name']}**
İlgi alanlarına uygun, keyifli bir etkinlik."""
            }