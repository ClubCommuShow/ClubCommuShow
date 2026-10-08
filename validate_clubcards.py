"""Validate numbers, automatic rarity/weights and registered image files."""
import json,re
from pathlib import Path
from PIL import Image

def validate(root=Path('.')):
 manifest=json.loads((root/'data/clubcard_manifest.json').read_text())
 rules=manifest['rarityRules'];seen=set();overrides=[]
 assert rules['mode']=='cardNumberLastDigit'
 for card in manifest['cards']:
  number=card['cardNumber'];assert re.fullmatch(r'[0-9]{5}',number),number
  assert int(number)==card['serial'] and number not in seen,number
  seen.add(number);assert isinstance(card['cardName'],str) and card['cardName'],number
  assert type(card['manualRarityWeightOverride']) is bool,number
  if card['manualRarityWeightOverride']:
   rarity=card['rarityOverride'];weight=card['weightOverride'];overrides.append(number)
  else:
   assert 'rarityOverride' not in card and 'weightOverride' not in card,number
   rarity=rules['byLastDigit'][number[-1]];weight=rules['defaultWeights'][rarity]
  assert rarity in rules['defaultWeights'] and type(weight) is int and weight>=0,number
  assert type(card['enabled']) is bool and type(card['exchangeEnabled']) is bool,number
  assert type(card['exchangePriceOverride']) is int and card['exchangePriceOverride']>=0,number
  assert card['imagePath']=='images/clubcards/cards/'+number+'.png',number
  with Image.open(root/card['imagePath']) as im:
   assert im.format=='PNG' and max(im.size)<=2048,number
   im.verify()
 print('PASS ClubCard:',len(seen),'cards; overrides:',','.join(overrides))
 return manifest

if __name__=='__main__':validate()
