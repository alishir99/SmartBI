import { FocusedCardPage } from './FocusedCardPage'

export function ProductsPage() {
  return (
    <FocusedCardPage
      title="Produkter"
      description="Dina produkter rangordnade efter nettoförsäljning."
      dimension="product"
      followUps={[
        'Vilka produkter tappade mest mot förra året?',
        'Vilka produkter säljer bäst online jämfört med i butik?',
        'Visa topp 10 produkter i Stockholms län',
        'Vilken produkt har högst snittpris?',
      ]}
    />
  )
}
