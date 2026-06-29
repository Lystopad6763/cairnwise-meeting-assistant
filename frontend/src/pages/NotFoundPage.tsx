import { useNavigate } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { Button, EmptyState } from '../components/ui';

/** Catch-all 404 route. Kept minimal and on-brand (matches EmptyState styling). */
export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto max-w-lg py-16">
      <EmptyState
        icon={Compass}
        title="Сторінку не знайдено"
        description="Такого маршруту немає. Можливо, посилання застаріле або ви перейшли за неіснуючою адресою."
        action={<Button onClick={() => navigate('/')}>До проєктів</Button>}
      />
    </div>
  );
}

export default NotFoundPage;
