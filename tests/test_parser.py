import unittest

from rutracker_tui.parser import parse_forum_topics, parse_forums, parse_size, parse_topic_details


class ParserTest(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(parse_size("1.5 GB")[1], 1610612736)
        self.assertEqual(parse_size("700 МБ")[1], 734003200)

    def test_parse_forums(self):
        html = '<tr><td>Книги и журналы</td><td><a href="viewforum.php?f=10">Аудиокниги</a></td></tr>'
        forums = parse_forums(html)
        self.assertEqual(forums[0].id, 10)
        self.assertEqual(forums[0].title, "Аудиокниги")
        self.assertEqual(forums[0].category, "Книги и журналы")

    def test_parse_forum_topics(self):
        html = """
        <tr>
          <td><a href="viewtopic.php?t=42">Ubuntu ISO</a></td>
          <td class="seedmed">11</td>
          <td class="leechmed">2</td>
          <td>4.7 GB</td>
        </tr>
        """
        topics = parse_forum_topics(html, forum_id=10)
        self.assertEqual(topics[0].id, 42)
        self.assertEqual(topics[0].seeders, 11)
        self.assertEqual(topics[0].size_text, "4.7 GB")

    def test_date_parser_does_not_mix_nicknames(self):
        html = """
        <tr>
          <td><a href="viewtopic.php?t=43">100</a></td>
          <td>54 GarfieldX 2026</td>
        </tr>
        """
        topics = parse_forum_topics(html, forum_id=10)
        self.assertIsNone(topics[0].registered_at)

    def test_parse_topic_details(self):
        html = """
        <html>
          <h1>Ubuntu ISO</h1>
          <td class="message">
            <img src="/pic/title.jpg">
            Описание релиза
          </td>
          <a href="magnet:?xt=urn:btih:abc">magnet</a>
          <table id="tor-filelist">
            <tr><td>ubuntu.iso</td><td>4.7 GB</td></tr>
          </table>
          <span class="seedmed">15</span>
        </html>
        """
        details = parse_topic_details(html, "https://rutracker.org/forum/viewtopic.php?t=42")
        self.assertEqual(details.id, 42)
        self.assertEqual(details.magnet, "magnet:?xt=urn:btih:abc")
        self.assertEqual(details.first_image_url, "https://rutracker.org/pic/title.jpg")
        self.assertEqual(details.files[0].path, "ubuntu.iso")
        self.assertEqual(details.seeders, 15)


if __name__ == "__main__":
    unittest.main()
